"""监控实例视图剩余动作：列表指标、主对象搜索、组织变更与鉴权失败。"""

import json
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.core.exceptions.base_app_exception import BaseAppException, UnauthorizedException
from apps.monitor.constants.permission import PermissionConstants
from apps.monitor.models.monitor_object import MonitorInstance, MonitorObject
from apps.monitor.views import monitor_instance as view_mod
from apps.monitor.views.monitor_instance import MonitorInstanceViewSet, _ensure_operate_instances

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _superuser():
    return UserFactory(domain="domain.com", is_superuser=True)


def _json(resp):
    return json.loads(resp.content)


def test_monitor_instance_list_converts_metrics_when_requested():
    user = _superuser()
    converted = []
    with (
        patch.object(view_mod, "get_current_team", return_value=1),
        patch.object(view_mod, "get_permission_rules", return_value={"instance": []}),
        patch.object(view_mod, "permission_filter", return_value="qs"),
        patch.object(view_mod, "parse_page_params", return_value=(1, 10)),
        patch.object(
            view_mod.MonitorObjectService,
            "get_monitor_instance",
            return_value={"results": [{"instance_id": "i1"}]},
        ),
        patch.object(
            view_mod.MetricsService,
            "convert_instance_list_metrics",
            side_effect=lambda oid, rows: converted.append((oid, [r["instance_id"] for r in rows])),
        ),
    ):
        request = factory.get("/5/list?add_metrics=true")
        force_authenticate(request, user=user)
        request.COOKIES["current_team"] = "1"
        resp = MonitorInstanceViewSet.as_view({"get": "monitor_instance_list"})(request, monitor_object_id="5")
    assert resp.status_code == 200
    assert converted == [(5, ["i1"])]
    assert _json(resp)["data"]["results"][0]["permission"] == PermissionConstants.DEFAULT_PERMISSION


def test_monitor_instance_search_attaches_explicit_permission():
    user = _superuser()
    obj = MonitorObject.objects.create(name="SearchR13", level="base")

    class FakeSearch:
        def __init__(self, *args, **kwargs):
            pass

        def search(self):
            return {"results": [{"instance_id": "hit-1"}]}

    with (
        patch.object(view_mod, "get_current_team", return_value=1),
        patch.object(
            view_mod, "get_permission_rules",
            return_value={"instance": [{"id": "hit-1", "permission": ["Operate"]}]},
        ),
        patch.object(view_mod, "permission_filter", return_value="qs"),
        patch.object(view_mod, "InstanceSearch", FakeSearch),
    ):
        request = factory.post(f"/{obj.id}/search", {}, format="json")
        force_authenticate(request, user=user)
        request.COOKIES["current_team"] = "1"
        resp = MonitorInstanceViewSet.as_view({"post": "monitor_instance_search"})(request, monitor_object_id=str(obj.id))
    assert _json(resp)["data"]["results"][0]["permission"] == ["Operate"]


def test_effective_plugins_requires_instance_id():
    user = _superuser()
    request = factory.get("/1/effective_plugins")
    force_authenticate(request, user=user)
    request.COOKIES["current_team"] = "1"
    with pytest.raises(BaseAppException, match="instance_id is required"):
        MonitorInstanceViewSet().effective_plugins(request, "1")


def test_list_by_primary_object_attaches_permissions():
    user = _superuser()
    obj = MonitorObject.objects.create(name="PrimaryR13", level="base")

    class FakeSearch:
        def __init__(self, *args, **kwargs):
            pass

        def search_by_primary_object(self):
            return {"results": [{"instance_id": "p1"}, {"instance_id": "p2"}]}

    with (
        patch.object(view_mod, "get_current_team", return_value=1),
        patch.object(
            view_mod, "get_permission_rules",
            return_value={"instance": [{"id": "p1", "permission": ["View"]}]},
        ),
        patch.object(view_mod, "permission_filter", return_value="qs"),
        patch.object(view_mod, "InstanceSearch", FakeSearch),
    ):
        request = factory.post(f"/{obj.id}/list_by_primary_object", {}, format="json")
        force_authenticate(request, user=user)
        request.COOKIES["current_team"] = "1"
        resp = MonitorInstanceViewSet.as_view({"post": "list_by_primary_object"})(
            request, monitor_object_id=str(obj.id),
        )
    rows = {item["instance_id"]: item["permission"] for item in _json(resp)["data"]["results"]}
    assert rows["p1"] == ["View"]
    assert rows["p2"] == PermissionConstants.DEFAULT_PERMISSION


def test_generate_check_and_autodiscover_delegate_to_service():
    user = _superuser()
    with patch.object(
        view_mod.MonitorObjectService, "generate_monitor_instance_id", return_value={"id": "gen-1"},
    ) as gen:
        request = factory.post(
            "/3/generate_instance_id",
            {"monitor_instance_name": "n", "interval": 60},
            format="json",
        )
        force_authenticate(request, user=user)
        resp = MonitorInstanceViewSet.as_view({"post": "generate_monitor_instance_id"})(request, monitor_object_id="3")
    gen.assert_called_once_with(3, "n", 60)
    assert _json(resp)["data"] == {"id": "gen-1"}

    with patch.object(view_mod.MonitorObjectService, "check_monitor_instance") as check:
        request = factory.post("/3/check_monitor_instance", {"name": "n"}, format="json")
        force_authenticate(request, user=user)
        resp = MonitorInstanceViewSet.as_view({"post": "check_monitor_instance"})(request, monitor_object_id="3")
    check.assert_called_once()
    assert resp.status_code == 200
    assert _json(resp)["result"] is True

    with patch.object(view_mod.MonitorObjectService, "autodiscover_monitor_instance") as auto:
        request = factory.get("/autodiscover_monitor_instance")
        force_authenticate(request, user=user)
        resp = MonitorInstanceViewSet.as_view({"get": "autodiscover_monitor_instance"})(request)
    auto.assert_called_once()
    assert _json(resp)["result"] is True


def test_update_and_organization_mutation_actions():
    user = _superuser()
    obj = MonitorObject.objects.create(name="MutR13", level="base")
    inst = MonitorInstance.objects.create(id="('mut-r13',)", name="m", monitor_object=obj)
    actor = {
        "username": user.username, "domain": user.domain, "current_team": 1,
        "include_children": False, "is_superuser": True, "group_list": [],
    }

    with (
        patch.object(view_mod, "_build_actor_context", return_value=actor),
        patch.object(view_mod, "_ensure_operate_instances", return_value=[inst.id]),
        patch.object(view_mod, "_ensure_target_organizations"),
        patch.object(view_mod.MonitorObjectService, "update_instance") as update,
    ):
        request = factory.post(
            "/update_monitor_instance",
            {"instance_id": inst.id, "name": "nn", "organizations": [1]},
            format="json",
        )
        force_authenticate(request, user=user)
        resp = MonitorInstanceViewSet.as_view({"post": "update_monitor_instance"})(request)
    update.assert_called_once_with(inst.id, "nn", [1])
    assert resp.status_code == 200

    mutations = [
        ("instances_remove_organizations", "remove_instances_organizations"),
        ("instances_add_organizations", "add_instances_organizations"),
        ("set_instances_organizations", "set_instances_organizations"),
    ]
    for action, method in mutations:
        with (
            patch.object(view_mod, "_build_actor_context", return_value=actor),
            patch.object(view_mod, "_ensure_operate_instances", return_value=[inst.id]),
            patch.object(view_mod, "_ensure_target_organizations"),
            patch.object(view_mod.MonitorObjectService, method) as svc,
        ):
            request = factory.post(
                f"/{action}",
                {"instance_ids": [inst.id], "organizations": [2]},
                format="json",
            )
            force_authenticate(request, user=user)
            resp = MonitorInstanceViewSet.as_view({"post": action})(request)
        svc.assert_called_once_with([inst.id], [2])
        assert resp.status_code == 200
        assert _json(resp)["result"] is True


def test_ensure_operate_instances_missing_and_unauthorized(monkeypatch):
    obj = MonitorObject.objects.create(name="AuthR13", level="base")
    inst = MonitorInstance.objects.create(id="('auth-r13',)", name="a", monitor_object=obj)
    actor = {
        "username": "u", "domain": "d", "current_team": 1,
        "include_children": False, "is_superuser": False, "group_list": [1],
    }

    assert _ensure_operate_instances(None, [], actor) == []

    with pytest.raises(BaseAppException, match="监控实例不存在"):
        _ensure_operate_instances(None, ["missing-id"], actor)

    class EmptyQS:
        def filter(self, **kwargs):
            return self

        def values_list(self, *args, **kwargs):
            return []

    monkeypatch.setattr(
        view_mod.InstanceConfigService,
        "_get_authorized_monitor_instances",
        staticmethod(lambda *a, **k: EmptyQS()),
    )
    monkeypatch.setattr(view_mod, "_ensure_instance_scope", lambda ids, ctx: ids)
    with pytest.raises(UnauthorizedException, match="无权限操作指定监控实例"):
        _ensure_operate_instances(None, [inst.id], actor)
