"""CollectModelViewSet 权限裁剪与派发：无组织、实例/团队裁剪、执行拒绝。"""
import json
from types import SimpleNamespace

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.cmdb.constants.constants import CollectPluginTypes, CollectRunStatusType
from apps.cmdb.models.collect_model import CollectModels
from apps.cmdb.views.collect import CollectModelViewSet
from apps.core.exceptions.base_app_exception import BaseAppException

VIEWS = "apps.cmdb.views.collect"


@pytest.fixture
def superuser(authenticated_user):
    u = authenticated_user
    u.is_superuser = True
    u.group_list = [{"id": 1}]
    u.roles = ["admin"]
    return u


def _req(method, user, data=None, team="1", include_children="0"):
    factory = APIRequestFactory()
    fn = getattr(factory, method)
    request = fn("/x/") if data is None else fn("/x/", data=data, format="json")
    request.COOKIES["current_team"] = team
    request.COOKIES["include_children"] = include_children
    force_authenticate(request, user=user)
    return request


def _body(response):
    if hasattr(response, "render"):
        response.render()
        return json.loads(response.rendered_content)
    return json.loads(response.content)


def _task(**kwargs):
    defaults = dict(
        name="collect-perm",
        task_type=CollectPluginTypes.HOST,
        model_id="host",
        cycle_value_type="cycle",
        team=[1],
        exec_status=CollectRunStatusType.SUCCESS,
    )
    defaults.update(kwargs)
    return CollectModels.objects.create(**defaults)


def test_get_queryset_by_permission_empty_without_team(superuser):
    task = _task()
    view = CollectModelViewSet()
    request = SimpleNamespace(COOKIES={}, user=superuser)
    qs = view.get_queryset_by_permission(request, CollectModels.objects.all())
    assert list(qs.values_list("id", flat=True)) == []
    assert task.id not in qs.values_list("id", flat=True)


def test_get_queryset_by_permission_filters_by_team(superuser, monkeypatch):
    visible = _task(name="visible", team=[1])
    _task(name="hidden", team=[9])
    monkeypatch.setattr(f"{VIEWS}.get_current_team_from_request", lambda request, required=False: 1)
    monkeypatch.setattr(f"{VIEWS}.get_permission_rules", lambda *a, **k: {})
    view = CollectModelViewSet()
    request = SimpleNamespace(COOKIES={"include_children": "0"}, user=superuser)
    qs = view.get_queryset_by_permission(request, CollectModels.objects.all())
    assert list(qs.values_list("id", flat=True)) == [visible.id]


def test_get_queryset_by_permission_instance_and_team_union(superuser, monkeypatch):
    inst_task = _task(name="inst", team=[1])
    team_task = _task(name="team-ok", team=[2])
    _task(name="other", team=[3])
    monkeypatch.setattr(f"{VIEWS}.get_current_team_from_request", lambda request, required=False: 1)
    monkeypatch.setattr(f"{VIEWS}.get_current_team", lambda request, default=None: "1")
    monkeypatch.setattr(f"{VIEWS}.GroupUtils.get_group_with_descendants", lambda team: [1, 2])
    monkeypatch.setattr(
        f"{VIEWS}.get_permission_rules",
        lambda *a, **k: {"instance": [{"id": inst_task.id}], "team": [{"id": 2}]},
    )
    view = CollectModelViewSet()
    request = SimpleNamespace(COOKIES={"include_children": "1"}, user=superuser)
    ids = set(view.get_queryset_by_permission(request, CollectModels.objects.all()).values_list("id", flat=True))
    assert ids == {inst_task.id, team_task.id}


def test_exec_task_forbids_without_permission(superuser, monkeypatch):
    task = _task()
    monkeypatch.setattr(CollectModelViewSet, "get_object", lambda self: task)
    monkeypatch.setattr(CollectModelViewSet, "get_has_permission", lambda *a, **k: False)
    monkeypatch.setattr(f"{VIEWS}.get_current_team_from_request", lambda request: 1)
    with pytest.raises(BaseAppException, match="您没有操作该采集任务的权限！"):
        CollectModelViewSet.as_view({"post": "exec_task"})(_req("post", superuser), pk=task.id)


def test_create_update_destroy_dispatch_to_service(superuser, monkeypatch):
    monkeypatch.setattr(f"{VIEWS}.CollectModelService.create", lambda request, view: {"id": 11})
    monkeypatch.setattr(f"{VIEWS}.CollectModelService.update", lambda request, view: {"id": 12})
    monkeypatch.setattr(f"{VIEWS}.CollectModelService.destroy", lambda request, view: 13)
    created = CollectModelViewSet.as_view({"post": "create"})(_req("post", superuser, data={"name": "n"}))
    updated = CollectModelViewSet.as_view({"put": "update"})(_req("put", superuser, data={"name": "n"}), pk=1)
    deleted = CollectModelViewSet.as_view({"delete": "destroy"})(_req("delete", superuser), pk=1)
    assert _body(created)["data"] == {"id": 11}
    assert _body(updated)["data"] == {"id": 12}
    assert _body(deleted)["data"] == 13


def test_network_config_file_supported_brands(superuser):
    response = CollectModelViewSet.as_view({"get": "network_config_file_supported_brands"})(_req("get", superuser))
    assert response.data["items"][0]["device_type"] == "huawei"
    assert {item["device_type"] for item in response.data["items"]} >= {"huawei", "cisco_ios"}


def test_build_region_query_credential_uses_task_decrypt(superuser, monkeypatch):
    task = SimpleNamespace(
        id=99,
        decrypt_credentials={"ak": "secret", "model_id": "aws_account"},
        driver_type="job",
    )
    monkeypatch.setattr(CollectModelViewSet, "_get_authorized_task", lambda self, request, task_id: task)

    class Params:
        @staticmethod
        def build_region_credential(raw):
            return {"region": "cn-north-1", "ak": raw["ak"]}

    monkeypatch.setattr(f"{VIEWS}.NodeParamsFactory.get_params_class", lambda model_id, driver: Params)
    view = CollectModelViewSet()
    out = view._build_region_query_credential(
        _req("post", superuser),
        {"model_id": "aws_account", "driver_type": "job"},
        task_id=task.id,
    )
    assert out["model_id"] == "aws"
    assert out["region"] == "cn-north-1"
    assert out["ak"] == "secret"
