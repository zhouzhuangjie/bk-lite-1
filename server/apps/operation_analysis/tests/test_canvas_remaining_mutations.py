"""仪表盘/拓扑/架构/大屏/报表：list/retrieve、内置拒绝、普通 destroy 与 PATCH。"""
import json

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.operation_analysis.models.models import Architecture, Dashboard, Directory, Report, Screen, Topology
from apps.operation_analysis.views import view as view_module
from apps.system_mgmt.models import OperationLog

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


def _superuser(user):
    user.is_superuser = True
    return user


def _req(method, path, user, data=None):
    fn = getattr(factory, method)
    request = fn(path, data=data, format="json") if data is not None else fn(path)
    request.COOKIES["current_team"] = "1"
    request.COOKIES["include_children"] = "0"
    force_authenticate(request, user=user)
    return request


def _render(resp):
    resp.render()
    if not resp.content:
        return None
    return json.loads(resp.content.decode("utf-8"))


def _screen_view_sets():
    return {"viewport": {"width": 1920, "height": 1080}, "items": [], "decorations": {}}


@pytest.mark.parametrize(
    "model,viewset,label,extra",
    [
        (Dashboard, view_module.DashboardModelViewSet, "仪表盘", {}),
        (Topology, view_module.TopologyModelViewSet, "拓扑图", {}),
        (Architecture, view_module.ArchitectureModelViewSet, "架构图", {}),
        (Screen, view_module.ScreenModelViewSet, "大屏", {"view_sets": _screen_view_sets()}),
        (Report, view_module.ReportModelViewSet, "报表", {}),
    ],
    ids=["dashboard", "topology", "architecture", "screen", "report"],
)
def test_canvas_list_retrieve_update_destroy_and_builtin_forbidden(authenticated_user, monkeypatch, model, viewset, label, extra):
    user = _superuser(authenticated_user)
    monkeypatch.setattr(
        "apps.core.utils.viewset_utils.get_permission_rules",
        lambda *a, **k: {"instance": [], "team": ["1"]},
    )
    directory = Directory.objects.create(name=f"{label}目录", groups=[1], created_by="testuser")
    obj = model.objects.create(name=f"{label}A", groups=[1], directory=directory, created_by="testuser", **extra)
    builtin = model.objects.create(
        name=f"内置{label}",
        groups=[1],
        directory=directory,
        is_build_in=True,
        build_in_key=f"bk-{label}",
        **extra,
    )

    listed = viewset.as_view({"get": "list"})(_req("get", "/x/", user))
    payload = _render(listed)
    assert listed.status_code == status.HTTP_200_OK
    data = payload["data"]
    items = data["items"] if isinstance(data, dict) else data
    names = {item["name"] for item in items}
    assert f"{label}A" in names

    retrieved = viewset.as_view({"get": "retrieve"})(_req("get", "/x/", user), pk=str(obj.id))
    payload = _render(retrieved)
    assert retrieved.status_code == status.HTTP_200_OK
    assert payload["data"]["name"] == f"{label}A"

    update_data = {"name": f"{label}B", "groups": [1], "directory": directory.id}
    if "view_sets" in extra:
        update_data["view_sets"] = extra["view_sets"]
    updated = viewset.as_view({"put": "update"})(_req("put", "/x/", user, data=update_data), pk=str(obj.id))
    payload = _render(updated)
    assert updated.status_code == status.HTTP_200_OK
    obj.refresh_from_db()
    assert obj.name == f"{label}B"
    assert OperationLog.objects.filter(summary=f"编辑{label}: {label}B").exists()

    patched = viewset.as_view({"patch": "partial_update"})(
        _req("patch", "/x/", user, data={"desc": "新描述"}),
        pk=str(obj.id),
    )
    payload = _render(patched)
    assert patched.status_code == status.HTTP_200_OK
    obj.refresh_from_db()
    assert obj.desc == "新描述"

    forbidden = viewset.as_view({"delete": "destroy"})(_req("delete", "/x/", user), pk=str(builtin.id))
    _render(forbidden)
    assert forbidden.status_code == status.HTTP_403_FORBIDDEN
    assert model.objects.filter(id=builtin.id).exists()

    deleted = viewset.as_view({"delete": "destroy"})(_req("delete", "/x/", user), pk=str(obj.id))
    _render(deleted)
    assert not model.objects.filter(id=obj.id).exists()
    assert OperationLog.objects.filter(summary=f"删除{label}: {label}B").exists()
