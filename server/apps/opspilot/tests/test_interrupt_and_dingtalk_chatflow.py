"""ChatFlow 中断与钉钉入口：缺参 400、无执行 404、GET 健康检查。"""
import json
from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from apps.opspilot import views as opspilot_views

pytestmark = pytest.mark.django_db
factory = RequestFactory()


def test_interrupt_chat_flow_rejects_invalid_json_and_missing_id(monkeypatch):
    monkeypatch.setattr(opspilot_views, "get_loader", lambda request: {"error.execution_id_required": "execution_id is required"})
    req = factory.post("/interrupt/", data="not-json", content_type="application/json")
    resp = opspilot_views.interrupt_chat_flow_execution(req)
    assert resp.status_code == 400

    req2 = factory.post("/interrupt/", data=json.dumps({}), content_type="application/json")
    resp2 = opspilot_views.interrupt_chat_flow_execution(req2)
    assert resp2.status_code == 400
    body = json.loads(resp2.content)
    assert body["result"] is False


def test_interrupt_chat_flow_not_found_for_other_team(monkeypatch):
    monkeypatch.setattr(opspilot_views, "get_loader", lambda request: {"error.execution_not_found": "Execution not found"})
    monkeypatch.setattr(opspilot_views, "extract_api_token", lambda request: "tok")
    monkeypatch.setattr(opspilot_views, "get_current_team", lambda request: 1)
    monkeypatch.setattr(
        opspilot_views,
        "validate_openai_token",
        lambda token, team: (True, SimpleNamespace(team=1)),
    )
    req = factory.post(
        "/interrupt/",
        data=json.dumps({"execution_id": "exec-missing", "reason": "stop"}),
        content_type="application/json",
    )
    resp = opspilot_views.interrupt_chat_flow_execution(req)
    assert resp.status_code == 404
    assert json.loads(resp.content)["result"] is False


def test_execute_chat_flow_dingtalk_get_health():
    req = factory.get("/dingtalk/12/")
    resp = opspilot_views.execute_chat_flow_dingtalk(req, bot_id=12)
    body = json.loads(resp.content)
    assert body["status"] == "ok"
    assert body["bot_id"] == 12
