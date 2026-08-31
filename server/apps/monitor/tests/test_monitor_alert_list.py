"""MonitorAlertViewSet.list：无权限空列表；按对象过滤分页。"""
import json

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.monitor.models import MonitorAlert
from apps.monitor.models.monitor_object import MonitorObject
from apps.monitor.models.monitor_policy import MonitorPolicy
from apps.monitor.views.monitor_alert import MonitorAlertViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _user():
    u = UserFactory(domain="domain.com", is_superuser=True)
    u.permission = {"monitor": set()}
    return u


def test_alert_list_returns_empty_when_no_accessible_policies(monkeypatch):
    user = _user()
    monkeypatch.setattr(
        MonitorAlertViewSet,
        "_get_all_accessible_policy_ids",
        lambda self, request: [],
    )
    request = factory.get("/api/v1/monitor/api/monitor_alert/")
    force_authenticate(request, user=user)
    request.COOKIES["current_team"] = "1"
    view = MonitorAlertViewSet.as_view({"get": "list"})
    resp = view(request)
    body = json.loads(resp.content)
    assert body["data"]["count"] == 0
    assert body["data"]["results"] == []


def test_alert_list_filters_by_object_and_paginates(monkeypatch):
    user = _user()
    obj = MonitorObject.objects.create(name="AlertListObj", level="base")
    policy = MonitorPolicy.objects.create(
        monitor_object=obj, name="p", algorithm="max", query_condition={}, source={}, group_by=[]
    )
    MonitorAlert.objects.create(policy_id=policy.id, monitor_instance_id="h1", status="new")
    MonitorAlert.objects.create(policy_id=policy.id, monitor_instance_id="h2", status="closed")

    monkeypatch.setattr(
        "apps.monitor.views.monitor_alert.get_permission_rules",
        lambda *a, **k: {"instance": [], "team": [1]},
    )
    monkeypatch.setattr(
        "apps.monitor.views.monitor_alert.permission_filter",
        lambda model, permission, **kwargs: model.objects.all(),
    )

    request = factory.get(
        f"/api/v1/monitor/api/monitor_alert/?monitor_object_id={obj.id}&page=1&page_size=10"
    )
    force_authenticate(request, user=user)
    request.COOKIES["current_team"] = "1"
    view = MonitorAlertViewSet.as_view({"get": "list"})
    resp = view(request)
    body = json.loads(resp.content)
    assert body["data"]["count"] == 2
    ids = {item["monitor_instance_id"] for item in body["data"]["results"]}
    assert ids == {"h1", "h2"}
