"""execute_chat_flow：非法 JSON、无工作流、pending 短路、测试互斥、流式/同步与异常。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.test import RequestFactory

from apps.opspilot import views

pytestmark = pytest.mark.django_db
rf = RequestFactory()


def _user(**overrides):
    data = dict(username="alice", domain="d", team=1, locale="en", group_list=[])
    data.update(overrides)
    return SimpleNamespace(**data)


def _loader():
    return SimpleNamespace(get=lambda key, default=None: default)


def _auth(monkeypatch, user=None):
    monkeypatch.setattr(views, "get_loader", lambda request=None, default_lang="en": _loader())
    monkeypatch.setattr(views, "extract_api_token", lambda request: "tok")
    monkeypatch.setattr(views, "get_current_team", lambda request: 1)
    monkeypatch.setattr(views, "validate_openai_token", lambda *a, **k: (True, user or _user()))


def _bot_qs(bot):
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.first.return_value = bot
    return qs


def _workflow(flow_json=None):
    wf = MagicMock()
    wf.first.return_value = SimpleNamespace(id=1, flow_json=flow_json if flow_json is not None else {"nodes": [{"id": "n1"}]})
    return wf


def _engine(node_type="restful"):
    engine = MagicMock()
    engine.execution_id = "exec-1"
    engine._get_node_by_id.return_value = {"type": node_type}
    return engine


def _post(body):
    return rf.post("/", data=json.dumps(body).encode("utf-8"), content_type="application/json")


@pytest.mark.asyncio
async def test_execute_chat_flow_rejects_invalid_json(monkeypatch):
    _auth(monkeypatch)
    req = rf.post("/", data=b"{bad", content_type="application/json")
    resp = await views.execute_chat_flow(req, bot_id=8, node_id="n1")
    assert resp.status_code == 400
    assert json.loads(resp.content) == {"result": False, "message": "Invalid JSON payload"}


@pytest.mark.asyncio
async def test_execute_chat_flow_requires_workflow_and_flow_json(monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(views.Bot.objects, "filter", lambda *a, **k: _bot_qs(SimpleNamespace(id=8)))
    wf = MagicMock()
    wf.first.return_value = None
    monkeypatch.setattr(views.BotWorkFlow.objects, "filter", lambda **k: wf)
    req = _post({"message": "hi"})
    missing = await views.execute_chat_flow(req, bot_id=8, node_id="n1")
    assert json.loads(missing.content) == {"result": False, "message": "No chat flow configured for this bot."}

    wf.first.return_value = SimpleNamespace(id=1, flow_json=None)
    empty = await views.execute_chat_flow(req, bot_id=8, node_id="n1")
    assert json.loads(empty.content) == {"result": False, "message": "Chat flow configuration is empty."}


@pytest.mark.asyncio
async def test_execute_chat_flow_delivers_pending_and_skips_new_run(monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(views.Bot.objects, "filter", lambda *a, **k: _bot_qs(SimpleNamespace(id=8)))
    monkeypatch.setattr(views.BotWorkFlow.objects, "filter", lambda **k: _workflow())
    monkeypatch.setattr(
        views,
        "try_deliver_to_pending",
        lambda bot_id, session_id, message: {"execution_id": "exec-9", "node_id": "wait-1"},
    )
    engine = MagicMock()
    monkeypatch.setattr(views, "create_chat_flow_engine", engine)
    req = _post({"message": "选择按类别", "session_id": "s1"})
    resp = await views.execute_chat_flow(req, bot_id=8, node_id="n1")
    body = json.loads(resp.content)
    assert body == {"result": True, "data": {"execution_id": "exec-9", "node_id": "wait-1"}}
    engine.assert_not_called()


@pytest.mark.asyncio
async def test_execute_chat_flow_rejects_second_running_test(monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(views.Bot.objects, "filter", lambda *a, **k: _bot_qs(SimpleNamespace(id=8)))
    monkeypatch.setattr(views.BotWorkFlow.objects, "filter", lambda **k: _workflow())
    monkeypatch.setattr(views, "create_chat_flow_engine", lambda *a, **k: _engine("agents"))
    running = MagicMock()
    running.exists.return_value = True
    monkeypatch.setattr(views.WorkFlowTaskResult.objects, "filter", lambda **k: running)
    delay = MagicMock()
    monkeypatch.setattr(views.chat_flow_test_execute_task, "delay", delay)
    resp = await views.execute_chat_flow(_post({"message": "hi", "is_test": True}), bot_id=8, node_id="n1")
    assert json.loads(resp.content) == {
        "result": False,
        "message": "A workflow test execution is already running for this bot.",
    }
    delay.assert_not_called()


@pytest.mark.asyncio
async def test_execute_chat_flow_sse_and_sync_and_exception(monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(views.Bot.objects, "filter", lambda *a, **k: _bot_qs(SimpleNamespace(id=8)))
    monkeypatch.setattr(views.BotWorkFlow.objects, "filter", lambda **k: _workflow())
    monkeypatch.setattr(views, "try_deliver_to_pending", lambda *a, **k: None)

    sse_engine = _engine("openai")
    sse_engine.sse_execute.return_value = "sse-response"
    monkeypatch.setattr(views, "create_chat_flow_engine", lambda *a, **k: sse_engine)
    sse = await views.execute_chat_flow(_post({"message": "stream me", "session_id": ""}), bot_id=8, node_id="n1")
    assert sse == "sse-response"
    sse_engine.sse_execute.assert_called_once()
    assert sse_engine.sse_execute.call_args.args[0]["last_message"] == "stream me"
    assert sse_engine.sse_execute.call_args.args[0]["entry_type"] == "openai"

    sync_engine = _engine("restful")
    sync_engine.execute.return_value = "plain-ok"
    monkeypatch.setattr(views, "create_chat_flow_engine", lambda *a, **k: sync_engine)
    sync = await views.execute_chat_flow(_post({"message": "run sync"}), bot_id=8, node_id="n1")
    body = json.loads(sync.content)
    assert body["result"] is True
    assert body["data"]["content"] == "plain-ok"
    assert "execution_time" in body["data"]
    sync_engine.execute.assert_called_once()

    monkeypatch.setattr(views, "create_chat_flow_engine", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("engine-down")))
    monkeypatch.setattr(views, "create_error_stream_response", lambda msg: f"stream-error:{msg}")
    failed = await views.execute_chat_flow(_post({"message": "boom"}), bot_id=8, node_id="n1")
    assert failed == "stream-error:engine-down"
