"""monitor NATS：query_latest_active_alerts 参数校验、对象存在性与授权实例过滤。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.monitor.models.monitor_object import MonitorInstance, MonitorObject
from apps.monitor.models.monitor_policy import MonitorAlert
from apps.monitor.nats import monitor as nm

pytestmark = pytest.mark.django_db


def test_query_latest_active_alerts_rejects_invalid_filters():
    over_limit = nm.query_latest_active_alerts({"limit": 200})
    assert over_limit["result"] is False
    assert "100" in over_limit["message"]

    bad_ids = nm.query_latest_active_alerts({"instance_ids": "h1"})
    assert bad_ids["result"] is False
    assert "列表" in bad_ids["message"]


def test_query_latest_active_alerts_missing_object():
    out = nm.query_latest_active_alerts({"monitor_obj_id": 999999}, user_info={})
    assert out["result"] is False
    assert "不存在" in out["message"]


def test_query_latest_active_alerts_empty_authorized_returns_zero():
    with patch.object(nm, "_get_authorized_monitor_instances", return_value=({}, None)):
        out = nm.query_latest_active_alerts({}, user_info={"user": SimpleNamespace(username="u")})
    assert out["result"] is True
    assert out["data"] == {"count": 0, "items": []}


def test_query_latest_active_alerts_returns_new_alerts_for_authorized_instance():
    obj = MonitorObject.objects.create(name="NATSAlertObj", level="base", display_name="告警对象")
    inst = MonitorInstance.objects.create(
        id="('alert-h1',)",
        name="alert-h1",
        monitor_object=obj,
        is_active=True,
        is_deleted=False,
    )
    MonitorAlert.objects.create(
        policy_id=1,
        monitor_instance_id=inst.id,
        monitor_instance_name="alert-h1",
        level="critical",
        status="new",
        content="cpu high",
        start_event_time=timezone.now(),
    )
    MonitorAlert.objects.create(
        policy_id=1,
        monitor_instance_id=inst.id,
        monitor_instance_name="alert-h1",
        level="warning",
        status="closed",
        content="old",
    )
    with patch.object(nm, "_get_authorized_monitor_instances", return_value=({inst.id: inst}, None)):
        out = nm.query_latest_active_alerts({"limit": 10})
    assert out["result"] is True
    assert out["data"]["count"] == 1
    item = out["data"]["items"][0]
    assert item["level"] == "critical"
    assert item["status"] == "new"
    assert item["monitor_object_name"] == "告警对象"
    assert item["end_event_time"] is None


def test_query_latest_active_alerts_denies_unauthorized_instance_filter():
    with patch.object(nm, "_get_authorized_monitor_instances", return_value=({"('ok',)": SimpleNamespace()}, None)):
        out = nm.query_latest_active_alerts({"instance_ids": ["('secret',)"]})
    assert out["result"] is False
    assert "没有权限" in out["message"]
