"""ConfigFileVersionViewSet 剩余错误路径：非法 ID、权限拒绝、读取失败与编码。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.cmdb.views.config_file import ConfigFileVersionViewSet
from apps.core.utils.web_utils import WebUtils

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()
VIEWS = "apps.cmdb.views.config_file"


@pytest.fixture
def superuser(authenticated_user):
    u = authenticated_user
    u.is_superuser = True
    u.group_list = [{"id": 1}]
    u.group_tree = []
    return u


def _req(method, user, data=None, query=""):
    fn = getattr(factory, method)
    path = "/x/" + (f"?{query}" if query else "")
    request = fn(path) if data is None else fn(path, data=data, format="json")
    request.COOKIES["current_team"] = "1"
    force_authenticate(request, user=user)
    return request


def _body(response):
    if hasattr(response, "render"):
        response.render()
        return json.loads(response.rendered_content)
    return json.loads(response.content)


def test_get_instance_or_error_empty_and_invalid_id(superuser):
    vs = ConfigFileVersionViewSet()
    inst, err = vs._get_instance_or_error("")
    assert inst is None
    assert err.status_code == status.HTTP_400_BAD_REQUEST
    assert _body(err)["message"] == "instance_id 不能为空"

    inst, err = vs._get_instance_or_error("abc")
    assert inst is None
    assert err.status_code == status.HTTP_400_BAD_REQUEST
    assert _body(err)["message"] == "instance_id 格式错误"


def test_list_permission_denied_and_status_filter(superuser, monkeypatch):
    monkeypatch.setattr(
        f"{VIEWS}.InstanceManage.query_entity_by_id",
        lambda pk: {"_id": pk, "model_id": "host", "organization": [1]},
    )
    denied = ConfigFileVersionViewSet()
    monkeypatch.setattr(
        ConfigFileVersionViewSet,
        "require_instance_permission",
        lambda self, request, instance, operator=None: WebUtils.response_403("抱歉！您没有此实例的权限"),
    )
    resp = ConfigFileVersionViewSet.as_view({"get": "list"})(
        _req("get", superuser, query="instance_id=5&file_path=/etc/app.conf")
    )
    assert resp.status_code == 403
    assert _body(resp)["message"] == "抱歉！您没有此实例的权限"

    monkeypatch.setattr(
        ConfigFileVersionViewSet,
        "require_instance_permission",
        lambda self, request, instance, operator=None: None,
    )
    qs = MagicMock()
    filtered = MagicMock()
    ordered = MagicMock()
    vs = ConfigFileVersionViewSet()
    vs.get_queryset = lambda: qs
    vs.paginate_queryset = lambda q: None
    vs.get_serializer = lambda q, many=True: SimpleNamespace(data=[{"id": 1}])
    qs.filter.return_value = filtered
    filtered.filter.return_value = filtered
    filtered.order_by.return_value = ordered
    request = _req("get", superuser, query="instance_id=5&file_path=/etc/a.conf&status=success")
    vs.request = request
    vs.format_kwarg = None
    resp = vs.list(request)
    assert resp.status_code == 200
    filtered.filter.assert_called_once_with(status="success")


def test_content_read_failure_and_unsupported_encoding(superuser, monkeypatch):
    monkeypatch.setattr(
        f"{VIEWS}.InstanceManage.query_entity_by_id",
        lambda pk: {"_id": pk, "model_id": "host", "organization": [1]},
    )
    monkeypatch.setattr(
        ConfigFileVersionViewSet,
        "require_instance_permission",
        lambda self, request, instance, operator=None: None,
    )

    class BoomVersion:
        id = 1
        instance_id = "5"
        content = "yes"

        def read_content_bytes(self):
            raise OSError("minio down")

    vs = ConfigFileVersionViewSet()
    vs.get_queryset = lambda: SimpleNamespace(filter=lambda **k: SimpleNamespace(first=lambda: BoomVersion()))
    resp = vs.content(_req("get", superuser), pk=1)
    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "读取配置文件内容失败" in _body(resp)["message"]

    class EncVersion:
        id = 2
        instance_id = "5"
        content = "yes"

        def read_content_bytes(self):
            return b"hello"

    vs.get_queryset = lambda: SimpleNamespace(filter=lambda **k: SimpleNamespace(first=lambda: EncVersion()))
    resp = vs.content(_req("get", superuser, query="encoding=not-a-codec"), pk=2)
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert _body(resp)["message"] == "不支持的编码: not-a-codec"


def test_content_success_returns_base64(superuser, monkeypatch):
    monkeypatch.setattr(
        f"{VIEWS}.InstanceManage.query_entity_by_id",
        lambda pk: {"_id": pk, "model_id": "host", "organization": [1]},
    )
    monkeypatch.setattr(
        ConfigFileVersionViewSet,
        "require_instance_permission",
        lambda self, request, instance, operator=None: None,
    )

    class OkVersion:
        id = 3
        instance_id = "5"
        content = "yes"

        def read_content_bytes(self):
            return b"abc"

    vs = ConfigFileVersionViewSet()
    vs.get_queryset = lambda: SimpleNamespace(filter=lambda **k: SimpleNamespace(first=lambda: OkVersion()))
    resp = vs.content(_req("get", superuser), pk=3)
    data = _body(resp)["data"]
    assert data["content"] == "abc"
    assert data["encoding"] == "utf-8"
    assert data["raw_base64"] == "YWJj"


def test_receive_result_rejects_non_object_and_create_manual_exception(superuser, monkeypatch):
    monkeypatch.setattr(
        f"{VIEWS}.InstanceManage.query_entity_by_id",
        lambda pk: {"_id": pk, "model_id": "host", "organization": [1]},
    )
    monkeypatch.setattr(
        ConfigFileVersionViewSet,
        "require_instance_permission",
        lambda self, request, instance, operator=None: None,
    )
    request = factory.post("/x/", ["not-object"], format="json")
    request.COOKIES["current_team"] = "1"
    force_authenticate(request, user=superuser)
    resp = ConfigFileVersionViewSet.as_view({"post": "receive_result"})(request)
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert _body(resp)["message"] == "请求体必须为 JSON 对象"

    monkeypatch.setattr(
        f"{VIEWS}.ConfigFileService.create_manual_version",
        lambda **k: (_ for _ in ()).throw(RuntimeError("disk full")),
    )
    resp = ConfigFileVersionViewSet.as_view({"post": "create_manual"})(
        _req(
            "post",
            superuser,
            data={"instance_id": "5", "model_id": "host", "file_path": "/a", "content": "x"},
        )
    )
    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "创建失败: disk full" in _body(resp)["message"]
