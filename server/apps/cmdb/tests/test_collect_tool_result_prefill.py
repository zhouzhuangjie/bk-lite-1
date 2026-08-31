"""CollectToolViewSet：脱敏凭据恢复失败、result 权限与 prefill 403/成功。"""
import json
from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.cmdb.services.collect_tool_service import MASKED_PASSWORD
from apps.cmdb.views.collect_tool import CollectToolViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _body(resp):
    return json.loads(resp.content.decode("utf-8"))


def _user():
    return UserFactory(is_superuser=True)


def _post(data, user=None):
    req = factory.post("/", data, format="json")
    force_authenticate(req, user=user or _user())
    req.COOKIES["current_team"] = "1"
    return CollectToolViewSet.as_view({"post": "execute"})(req)


def _get(action, params, user=None):
    req = factory.get("/", params)
    force_authenticate(req, user=user or _user())
    req.COOKIES["current_team"] = "1"
    return CollectToolViewSet.as_view({"get": action})(req)


def test_execute_ipmi_masked_password_without_task_id():
    payload = {
        "protocol": "ipmi",
        "action": "test_connection",
        "access_point_id": "ap-1",
        "target": "10.0.0.2",
        "port": 623,
        "credential": {"username": "root", "password": MASKED_PASSWORD},
    }
    with patch("apps.cmdb.views.collect_tool.CollectToolService.resolve_access_point", return_value="sg"):
        data = _body(_post(payload))["data"]
    assert data["status"] == "error"
    assert data["result"]["stage"] == "param"
    assert data["result"]["summary"] == "密码字段为脱敏占位，需要传入 task_id 以恢复原始凭据"


def test_execute_masked_credential_restore_validation_and_unexpected_error():
    payload = {
        "protocol": "snmp",
        "action": "test_connection",
        "access_point_id": "ap-1",
        "target": "10.0.0.1",
        "port": 161,
        "task_id": 88,
        "credential": {"version": "v2c", "community": MASKED_PASSWORD},
    }
    with (
        patch("apps.cmdb.views.collect_tool.CollectToolService.resolve_access_point", return_value="sg"),
        patch(
            "apps.cmdb.views.collect_tool.CollectToolService.get_accessible_task",
            side_effect=ValidationError("no access"),
        ),
    ):
        data = _body(_post(payload))["data"]
    assert data["status"] == "error"
    assert data["result"]["summary"] == "无法恢复原始凭据，请确认原任务可访问，或手动重新输入凭据"

    with (
        patch("apps.cmdb.views.collect_tool.CollectToolService.resolve_access_point", return_value="sg"),
        patch(
            "apps.cmdb.views.collect_tool.CollectToolService.get_accessible_task",
            side_effect=RuntimeError("decrypt boom"),
        ),
    ):
        data = _body(_post(payload))["data"]
    assert data["status"] == "error"
    assert data["result"]["summary"] == "无法恢复原始凭据，请确认原任务可访问，或手动重新输入凭据"


def test_result_not_found_forbidden_and_success():
    with patch("apps.cmdb.views.collect_tool.CollectToolService.get_debug_state", return_value=None):
        data = _body(_get("result", {"debug_id": "missing"}))["data"]
    assert data["status"] == "not_found"
    assert data["debug_id"] == "missing"

    with (
        patch(
            "apps.cmdb.views.collect_tool.CollectToolService.get_debug_state",
            return_value={"debug_id": "d1", "status": "pending", "owner": "other"},
        ),
        patch("apps.cmdb.views.collect_tool.CollectToolService.can_access_debug_state", return_value=False),
    ):
        resp = _get("result", {"debug_id": "d1"})
    assert resp.status_code == 403
    assert _body(resp)["message"] == "抱歉！您没有访问该调试结果的权限"
    assert "data" not in _body(resp)

    state = {"debug_id": "d2", "status": "success", "owner": "me"}
    with (
        patch("apps.cmdb.views.collect_tool.CollectToolService.get_debug_state", return_value=state),
        patch("apps.cmdb.views.collect_tool.CollectToolService.can_access_debug_state", return_value=True),
    ):
        data = _body(_get("result", {"debug_id": "d2"}))["data"]
    assert data == state


def test_prefill_forbidden_and_success():
    with patch(
        "apps.cmdb.views.collect_tool.CollectToolService.get_accessible_task",
        side_effect=ValidationError("no"),
    ):
        resp = _get("prefill", {"task_id": 1, "protocol": "snmp"})
    assert resp.status_code == 403
    body = _body(resp)
    assert body["result"] is False
    assert body["message"] == "抱歉！您没有访问该采集任务的权限"

    prefill = {"can_prefill": True, "target": "10.0.0.1"}
    with (
        patch("apps.cmdb.views.collect_tool.CollectToolService.get_accessible_task", return_value=object()),
        patch("apps.cmdb.views.collect_tool.CollectToolService.build_prefill", return_value=prefill),
    ):
        data = _body(_get("prefill", {"task_id": 2, "protocol": "ipmi"}))["data"]
    assert data == prefill
