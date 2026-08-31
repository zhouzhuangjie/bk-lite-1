"""监控 NATS 实例权限：缺用户 fail-closed；授权实例按权限过滤。"""
from types import SimpleNamespace

import pytest

from apps.monitor.models.monitor_object import MonitorInstance, MonitorInstanceOrganization, MonitorObject
from apps.monitor.nats import monitor as M

pytestmark = pytest.mark.django_db


def test_global_monitor_permissions_missing_user_or_team():
    data, teams, err = M._get_global_monitor_instance_permissions({"user": None, "team": 1})
    assert data is None and teams is None
    assert err["result"] is False
    assert "缺少用户或组织信息" in err["message"]
    data, teams, err = M._get_global_monitor_instance_permissions({"user": "alice", "team": None})
    assert err["result"] is False


def test_global_monitor_permissions_normalizes_non_dict_payload(monkeypatch):
    monkeypatch.setattr(M, "get_permissions_rules", lambda *a, **k: "bad")
    data, teams, err = M._get_global_monitor_instance_permissions({"user": "alice", "team": 7})
    assert err is None
    assert data == {}
    assert teams == []


def test_authorized_instances_empty_when_user_missing():
    instances, err = M._get_authorized_monitor_instances({"user": None, "team": 1})
    assert instances == {}
    assert err["result"] is False


def test_authorized_instances_keep_permitted_only(monkeypatch):
    obj = MonitorObject.objects.create(name="Host-nats-perm", level="base")
    allowed = MonitorInstance.objects.create(id="inst-ok", name="ok", monitor_object=obj)
    denied = MonitorInstance.objects.create(id="inst-no", name="no", monitor_object=obj)
    MonitorInstanceOrganization.objects.create(monitor_instance=allowed, organization=1)
    MonitorInstanceOrganization.objects.create(monitor_instance=denied, organization=1)
    monkeypatch.setattr(M, "_get_global_monitor_instance_permissions", lambda info: ({"p": 1}, [1], None))

    def _check(obj_id, inst_id, teams, perms, cur_team):
        return inst_id == "inst-ok"

    monkeypatch.setattr(M, "check_instance_permission", _check)
    authorized, err = M._get_authorized_monitor_instances({"user": "alice", "team": 1})
    assert err is None
    assert list(authorized) == ["inst-ok"]
    assert authorized["inst-ok"].id == allowed.id
