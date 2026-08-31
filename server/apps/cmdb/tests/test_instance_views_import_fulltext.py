"""InstanceViewSet 导入鉴权与全文检索参数契约。"""
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.cmdb.views.instance import InstanceViewSet
from apps.core.exceptions.base_app_exception import BaseAppException

VIEWS = "apps.cmdb.views.instance"


@pytest.fixture
def superuser(authenticated_user):
    u = authenticated_user
    u.is_superuser = True
    u.group_list = [{"id": 1}]
    u.group_tree = []
    u.roles = ["admin"]
    return u


@pytest.fixture
def normal_user(authenticated_user):
    u = authenticated_user
    u.is_superuser = False
    u.group_list = [{"id": 1}]
    u.group_tree = []
    u.roles = []
    return u


def _req(method, user, data=None, team=None, include_children="0", files=None):
    factory = APIRequestFactory()
    fn = getattr(factory, method)
    if files is not None:
        request = fn("/x/", data=files, format="multipart")
    elif data is None:
        request = fn("/x/")
    else:
        request = fn("/x/", data=data, format="json")
    if team is not None:
        request.COOKIES["current_team"] = team
    request.COOKIES["include_children"] = include_children
    force_authenticate(request, user=user)
    return request


def _body(response):
    if hasattr(response, "render"):
        response.render()
        return json.loads(response.rendered_content)
    return json.loads(response.content)


def _call(action_map, request, **kwargs):
    return InstanceViewSet.as_view(action_map)(request, **kwargs)


def test_inst_import_requires_selected_org(superuser):
    response = _call({"post": "inst_import"}, _req("post", superuser, team=None), model_id="host")
    body = _body(response)
    assert body["result"] is False
    assert body["message"] == "请先选择组织后再导入"
    assert body["data"] == []


def test_inst_import_rejects_invalid_org(superuser):
    response = _call({"post": "inst_import"}, _req("post", superuser, team="abc"), model_id="host")
    body = _body(response)
    assert body["result"] is False
    assert body["message"] == "当前组织参数无效，请刷新页面后重试"


def test_inst_import_forbids_unauthorized_org(normal_user, monkeypatch):
    normal_user.permission = {"asset_info-Add"}
    monkeypatch.setattr(
        f"{VIEWS}.GroupUtils.get_user_authorized_child_groups",
        lambda **kwargs: [],
    )
    response = _call({"post": "inst_import"}, _req("post", normal_user, team="1"), model_id="host")
    body = _body(response)
    assert body["result"] is False
    assert body["message"] == "抱歉！您没有该组织的权限或组织选择无效"


def test_inst_import_requires_excel_file(superuser, monkeypatch):
    monkeypatch.setattr(f"{VIEWS}.GroupUtils.get_all_child_groups", lambda *a, **k: [1])
    response = _call({"post": "inst_import"}, _req("post", superuser, team="1"), model_id="host")
    body = _body(response)
    assert body["result"] is False
    assert body["message"] == "请上传Excel文件"


def test_inst_import_returns_dict_result(superuser, monkeypatch):
    monkeypatch.setattr(f"{VIEWS}.GroupUtils.get_all_child_groups", lambda *a, **k: [1])
    monkeypatch.setattr(
        f"{VIEWS}.InstanceManage.inst_import_support_edit",
        lambda *args, **kwargs: {"success": True, "message": "导入成功 1 条"},
    )
    uploaded = SimpleUploadedFile(
        "host.xlsx",
        b"xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    request = _req("post", superuser, team="1", files={"file": uploaded})
    response = _call({"post": "inst_import"}, request, model_id="host")
    body = _body(response)
    assert body["result"] is True
    assert body["message"] == "导入成功 1 条"


def test_inst_import_legacy_string_failure(superuser, monkeypatch):
    monkeypatch.setattr(f"{VIEWS}.GroupUtils.get_all_child_groups", lambda *a, **k: [1])
    monkeypatch.setattr(
        f"{VIEWS}.InstanceManage.inst_import_support_edit",
        lambda *args, **kwargs: "数据导入失败: 格式错误",
    )
    uploaded = SimpleUploadedFile("host.xlsx", b"xlsx")
    request = _req("post", superuser, team="1", files={"file": uploaded})
    response = _call({"post": "inst_import"}, request, model_id="host")
    body = _body(response)
    assert body["result"] is False
    assert body["message"] == "数据导入失败: 格式错误"


def test_inst_import_exception_returns_failure(superuser, monkeypatch):
    monkeypatch.setattr(f"{VIEWS}.GroupUtils.get_all_child_groups", lambda *a, **k: [1])

    def boom(*args, **kwargs):
        raise ValueError("broken sheet")

    monkeypatch.setattr(f"{VIEWS}.InstanceManage.inst_import_support_edit", boom)
    uploaded = SimpleUploadedFile("host.xlsx", b"xlsx")
    request = _req("post", superuser, team="1", files={"file": uploaded})
    response = _call({"post": "inst_import"}, request, model_id="host")
    body = _body(response)
    assert body["result"] is False
    assert body["message"] == "数据导入异常，请检查文件格式和内容: broken sheet"


def test_fulltext_search_stats_requires_keyword(superuser, monkeypatch):
    monkeypatch.setattr(
        f"{VIEWS}.CmdbRulesFormatUtil.format_user_groups_permissions",
        lambda **k: {},
    )
    response = _call({"post": "fulltext_search_stats"}, _req("post", superuser, data={}))
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    body = _body(response)
    assert body["result"] is False
    assert body["data"] == "search keyword is required"
    assert body["message"] == ""


def test_fulltext_search_by_model_validates_required_and_page(superuser, monkeypatch):
    monkeypatch.setattr(
        f"{VIEWS}.CmdbRulesFormatUtil.format_user_groups_permissions",
        lambda **k: {},
    )
    view = {"post": "fulltext_search_by_model"}
    missing_search = _call(view, _req("post", superuser, data={"model_id": "host"}))
    assert _body(missing_search)["data"] == "search keyword is required"
    assert _body(missing_search)["message"] == ""

    missing_model = _call(view, _req("post", superuser, data={"search": "cpu"}))
    assert _body(missing_model)["data"] == "model_id is required"

    bad_page = _call(view, _req("post", superuser, data={"search": "cpu", "model_id": "host", "page": "x"}))
    assert _body(bad_page)["data"] == "page and page_size must be integers"

    page_zero = _call(view, _req("post", superuser, data={"search": "cpu", "model_id": "host", "page": 0}))
    assert _body(page_zero)["data"] == "page must be >= 1"

    page_size = _call(view, _req("post", superuser, data={"search": "cpu", "model_id": "host", "page_size": 101}))
    assert _body(page_size)["data"] == "page_size must be between 1 and 100"


def test_fulltext_search_by_model_ok(superuser, monkeypatch):
    monkeypatch.setattr(
        f"{VIEWS}.CmdbRulesFormatUtil.format_user_groups_permissions",
        lambda **k: {1: {}},
    )
    monkeypatch.setattr(
        f"{VIEWS}.InstanceManage.fulltext_search_by_model",
        lambda **kwargs: {"model_id": kwargs["model_id"], "total": 1, "page": kwargs["page"], "data": [{"id": 1}]},
    )
    response = _call(
        {"post": "fulltext_search_by_model"},
        _req("post", superuser, data={"search": "cpu", "model_id": "host", "page": 2, "page_size": 10}),
    )
    body = _body(response)
    assert body["result"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["page"] == 2


def test_get_allowed_org_ids_superuser_and_forbidden(monkeypatch):
    monkeypatch.setattr(f"{VIEWS}.get_current_team_from_request", lambda request: 1)
    admin = SimpleNamespace(is_superuser=True, group_list=[{"id": 1}])
    request = SimpleNamespace(user=admin, COOKIES={"include_children": "0"})
    assert InstanceViewSet._get_allowed_org_ids(request) == [1]

    monkeypatch.setattr(f"{VIEWS}.GroupUtils.get_all_child_groups", lambda *a, **k: [1, 2])
    request.COOKIES = {"include_children": "1"}
    assert InstanceViewSet._get_allowed_org_ids(request) == [1, 2]

    monkeypatch.setattr(f"{VIEWS}.GroupUtils.get_user_authorized_child_groups", lambda **k: [])
    request.user = SimpleNamespace(is_superuser=False, group_list=[{"id": 1}])
    request.COOKIES = {"include_children": "0"}
    with pytest.raises(BaseAppException, match="抱歉！您没有该组织的权限或组织选择无效"):
        InstanceViewSet._get_allowed_org_ids(request)


def test_check_instance_read_permission_paths(monkeypatch, superuser):
    view = InstanceViewSet()
    request = SimpleNamespace(user=superuser)
    monkeypatch.setattr(InstanceViewSet, "check_creator_and_organizations", lambda self, r, i: True)
    assert view._check_instance_read_permission(request, {"model_id": "host"}) is True

    monkeypatch.setattr(InstanceViewSet, "check_creator_and_organizations", lambda self, r, i: False)
    monkeypatch.setattr(InstanceViewSet, "organizations", lambda self, r, i: [])
    assert view._check_instance_read_permission(request, {"model_id": "host"}) is False

    monkeypatch.setattr(InstanceViewSet, "organizations", lambda self, r, i: [1])
    monkeypatch.setattr(f"{VIEWS}.CmdbRulesFormatUtil.format_user_groups_permissions", lambda **k: {})
    monkeypatch.setattr(f"{VIEWS}.CmdbRulesFormatUtil.has_object_permission", lambda **k: True)
    assert view._check_instance_read_permission(request, {"model_id": "host"}) is True


def test_topo_search_expand_post_validates_inst_id(superuser):
    view = {"post": "topo_search_expand_post"}
    missing = _call(view, _req("post", superuser, data={}))
    assert missing.status_code == status.HTTP_400_BAD_REQUEST
    assert _body(missing)["result"] is False
    assert _body(missing)["data"] == "inst_id不能为空"
    assert _body(missing)["message"] == ""

    bad = _call(view, _req("post", superuser, data={"inst_id": "x"}))
    assert _body(bad)["data"] == "inst_id不合法"


def test_topo_and_layout_not_found(superuser, monkeypatch):
    monkeypatch.setattr(f"{VIEWS}.InstanceManage.query_entity_by_id", lambda pk: None)
    for action in ("topo_search", "network_topo", "room_layout", "rack_layout"):
        body = _body(_call({"get": action}, _req("get", superuser), model_id="host", inst_id=1))
        assert body["result"] is False
        assert body["data"] == "实例不存在"
        assert body["message"] == ""


def test_list_proxys_skips_invalid_items(superuser, monkeypatch):
    monkeypatch.setattr(
        f"{VIEWS}.NodeMgmt.cloud_region_list",
        lambda self: [{"id": 1, "name": "default"}, {"id": None, "name": "x"}, "bad"],
    )
    response = _call({"get": "list_proxys"}, _req("get", superuser))
    assert _body(response)["data"] == [{"proxy_id": 1, "proxy_name": "default"}]


def test_download_template_and_export(superuser, monkeypatch):
    monkeypatch.setattr(
        f"{VIEWS}.InstanceManage.download_import_template",
        lambda model_id: io.BytesIO(b"template"),
    )
    monkeypatch.setattr(
        f"{VIEWS}.CmdbRulesFormatUtil.format_user_groups_permissions",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        f"{VIEWS}.InstanceManage.inst_export",
        lambda **k: io.BytesIO(b"export"),
    )
    template = _call({"get": "download_template"}, _req("get", superuser), model_id="host")
    assert template["Content-Disposition"] == "attachment;filename=host_import_template.xlsx"
    exported = _call({"post": "inst_export"}, _req("post", superuser, data={"inst_ids": [1]}), model_id="host")
    assert exported["Content-Disposition"] == "attachment;filename=host_export.xlsx"
