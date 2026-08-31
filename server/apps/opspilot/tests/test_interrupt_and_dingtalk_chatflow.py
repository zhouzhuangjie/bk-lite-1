"""ChatFlow 中断与钉钉入口：缺参 400、无执行 404、成功中断、GET 健康检查。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.test import RequestFactory

from apps.opspilot import views as opspilot_views
from apps.opspilot.enum import WorkFlowTaskStatus

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


def test_interrupt_chat_flow_marks_running_and_skips_finished(monkeypatch):
    monkeypatch.setattr(opspilot_views, "get_loader", lambda request: SimpleNamespace(get=lambda key, default=None: default))
    monkeypatch.setattr(opspilot_views, "extract_api_token", lambda request: "tok")
    monkeypatch.setattr(opspilot_views, "get_current_team", lambda request: 1)
    monkeypatch.setattr(
        opspilot_views,
        "validate_openai_token",
        lambda token, team: (True, SimpleNamespace(team=1)),
    )
    requested = MagicMock()
    monkeypatch.setattr(opspilot_views, "request_interrupt", requested)

    running = SimpleNamespace(status=WorkFlowTaskStatus.RUNNING, save=MagicMock(), finished_at=None)
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.order_by.return_value = qs
    qs.first.return_value = running
    monkeypatch.setattr(opspilot_views.WorkFlowTaskResult.objects, "filter", lambda **k: qs)

    req = factory.post(
        "/interrupt/",
        data=json.dumps({"execution_id": "exec-run", "reason": "stop"}),
        content_type="application/json",
    )
    resp = opspilot_views.interrupt_chat_flow_execution(req)
    body = json.loads(resp.content)
    assert body == {
        "result": True,
        "data": {
            "execution_id": "exec-run",
            "status": WorkFlowTaskStatus.INTERRUPTED,
            "interrupt_requested": True,
        },
    }
    requested.assert_called_once_with("exec-run", reason="stop")
    assert running.status == WorkFlowTaskStatus.INTERRUPTED
    running.save.assert_called_once_with(update_fields=["status", "finished_at"])

    done = SimpleNamespace(status=WorkFlowTaskStatus.SUCCESS, save=MagicMock())
    qs.first.return_value = done
    finished = opspilot_views.interrupt_chat_flow_execution(req)
    assert json.loads(finished.content)["data"]["status"] == WorkFlowTaskStatus.INTERRUPTED
    done.save.assert_not_called()
    assert done.status == WorkFlowTaskStatus.SUCCESS


def test_execute_chat_flow_dingtalk_get_health():
    req = factory.get("/dingtalk/12/")
    resp = opspilot_views.execute_chat_flow_dingtalk(req, bot_id=12)
    body = json.loads(resp.content)
    assert body["status"] == "ok"
    assert body["bot_id"] == 12
