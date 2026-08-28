"""CollectToolViewSet.execute：接入点失败、脱敏缺 task_id、成功入队返回 pending。"""
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
    if hasattr(resp, "content"):
        try:
            return json.loads(resp.content.decode("utf-8"))
        except Exception:
            pass
    return getattr(resp, "data", None)


def _payload(**overrides):
    data = {
        "protocol": "snmp",
        "action": "test_connection",
        "access_point_id": "ap-1",
        "target": "10.0.0.1",
        "port": 161,
        "credential": {"version": "v2c", "community": "public"},
    }
    data.update(overrides)
    return data


def _call(data, user=None):
    user = user or UserFactory(is_superuser=True)
    req = factory.post("/", data, format="json")
    force_authenticate(req, user=user)
    req.COOKIES["current_team"] = "1"
    return CollectToolViewSet.as_view({"post": "execute"})(req)


def test_execute_access_point_failure_returns_error_result():
    with patch(
        "apps.cmdb.views.collect_tool.CollectToolService.resolve_access_point",
        side_effect=ValidationError("bad ap"),
    ):
        resp = _call(_payload())
    body = _body(resp)
    assert resp.status_code == 200
    data = body.get("data", body)
    assert data["status"] == "error"
    assert "接入点解析失败" in data["result"]["summary"] or "接入点解析失败" in str(data)


def test_execute_masked_password_without_task_id_returns_param_error():
    payload = _payload(credential={"version": "v2c", "community": MASKED_PASSWORD})
    with patch(
        "apps.cmdb.views.collect_tool.CollectToolService.resolve_access_point",
        return_value="stargazer-1",
    ):
        resp = _call(payload)
    data = _body(resp).get("data", _body(resp))
    assert data["status"] == "error"
    blob = str(data)
    assert "task_id" in blob


def test_execute_enqueues_debug_task_as_pending():
    payload = _payload()
    with patch(
        "apps.cmdb.views.collect_tool.CollectToolService.resolve_access_point",
        return_value="stargazer-1",
    ), patch(
        "apps.cmdb.views.collect_tool.CollectToolService.create_debug_id",
        return_value="dbg-1",
    ), patch(
        "apps.cmdb.views.collect_tool.CollectToolService.enqueue_debug_task"
    ) as enqueue:
        resp = _call(payload)
    enqueue.assert_called_once()
    assert enqueue.call_args.args[0] == "dbg-1"
    assert enqueue.call_args.args[2] == "stargazer-1"
    data = _body(resp).get("data", _body(resp))
    assert data["status"] == "pending"
    assert data.get("debug_id") == "dbg-1" or "dbg-1" in str(data)
