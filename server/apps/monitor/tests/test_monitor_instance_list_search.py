"""监控实例列表/搜索：权限字段回填与对象不存在。"""
import json
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.constants.permission import PermissionConstants
from apps.monitor.models.monitor_object import MonitorObject
from apps.monitor.views.monitor_instance import MonitorInstanceViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _superuser():
    return UserFactory(domain="domain.com", is_superuser=True)


def test_query_params_enum_wraps_service_result():
    user = _superuser()
    with patch(
        "apps.monitor.views.monitor_instance.InstanceSearch.get_query_params_enum",
        return_value=["cpu", "mem"],
    ) as enum:
        request = factory.get("/query_params_enum/host/?monitor_object_id=3")
        force_authenticate(request, user=user)
        resp = MonitorInstanceViewSet.as_view({"get": "get_query_params_enum"})(request, name="host")
    body = json.loads(resp.content)
    assert body["result"] is True
    assert body["data"] == ["cpu", "mem"]
    enum.assert_called_once_with("host", "3")


def test_monitor_instance_list_attaches_instance_permission():
    user = _superuser()
    with (
        patch("apps.monitor.views.monitor_instance.get_current_team", return_value=1),
        patch(
            "apps.monitor.views.monitor_instance.get_permission_rules",
            return_value={"instance": [{"id": "i1", "permission": ["View"]}]},
        ),
        patch("apps.monitor.views.monitor_instance.permission_filter", return_value="qs"),
        patch("apps.monitor.views.monitor_instance.parse_page_params", return_value=(1, 10)),
        patch(
            "apps.monitor.views.monitor_instance.MonitorObjectService.get_monitor_instance",
            return_value={"results": [{"instance_id": "i1"}, {"instance_id": "i2"}]},
        ),
    ):
        request = factory.get("/5/list")
        force_authenticate(request, user=user)
        request.COOKIES["current_team"] = "1"
        resp = MonitorInstanceViewSet.as_view({"get": "monitor_instance_list"})(request, monitor_object_id="5")
    body = json.loads(resp.content)
    rows = {item["instance_id"]: item["permission"] for item in body["data"]["results"]}
    assert rows["i1"] == ["View"]
    assert rows["i2"] == PermissionConstants.DEFAULT_PERMISSION


def test_monitor_instance_search_missing_object_raises():
    user = _superuser()
    request = factory.post("/999999881/search", {}, format="json")
    force_authenticate(request, user=user)
    request.COOKIES["current_team"] = "1"
    with pytest.raises(BaseAppException, match="does not exist"):
        MonitorInstanceViewSet().monitor_instance_search(request, "999999881")


def test_monitor_instance_search_attaches_default_permission_and_metrics():
    user = _superuser()
    obj = MonitorObject.objects.create(name="SearchObj881", level="base")

    class FakeSearch:
        def __init__(self, *args, **kwargs):
            pass

        def search(self):
            return {"results": [{"instance_id": "s1"}]}

    converted = []
    with (
        patch("apps.monitor.views.monitor_instance.get_current_team", return_value=1),
        patch("apps.monitor.views.monitor_instance.get_permission_rules", return_value={"instance": []}),
        patch("apps.monitor.views.monitor_instance.permission_filter", return_value="qs"),
        patch("apps.monitor.views.monitor_instance.InstanceSearch", FakeSearch),
        patch(
            "apps.monitor.views.monitor_instance.MetricsService.convert_instance_list_metrics",
            side_effect=lambda oid, rows: converted.append((oid, [r["instance_id"] for r in rows])),
        ),
    ):
        request = factory.post(f"/{obj.id}/search", {"add_metrics": True}, format="json")
        force_authenticate(request, user=user)
        request.COOKIES["current_team"] = "1"
        resp = MonitorInstanceViewSet.as_view({"post": "monitor_instance_search"})(request, monitor_object_id=str(obj.id))
    body = json.loads(resp.content)
    assert body["data"]["results"][0]["permission"] == PermissionConstants.DEFAULT_PERMISSION
    assert converted == [(obj.id, ["s1"])]


def test_list_by_primary_object_rejects_missing_and_child_object():
    user = _superuser()
    request = factory.post("/999999882/list_by_primary_object", {}, format="json")
    force_authenticate(request, user=user)
    with pytest.raises(BaseAppException, match="does not exist"):
        MonitorInstanceViewSet().list_by_primary_object(request, "999999882")

    parent = MonitorObject.objects.create(name="PrimaryObj882", level="base")
    child = MonitorObject.objects.create(name="ChildObj882", level="derivative", parent=parent)
    request = factory.post(f"/{child.id}/list_by_primary_object", {}, format="json")
    force_authenticate(request, user=user)
    with pytest.raises(BaseAppException, match="Only primary"):
        MonitorInstanceViewSet().list_by_primary_object(request, str(child.id))
