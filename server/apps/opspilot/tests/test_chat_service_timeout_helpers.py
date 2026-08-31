"""ChatService 超时预算与 eventlet 探测。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.services.chat_service import _cancel_all_tasks, _is_eventlet_environment, _resolve_agent_execute_timeout

pytestmark = pytest.mark.unit


def test_resolve_agent_execute_timeout_prefers_agent_env(monkeypatch):
    monkeypatch.delenv("AGENT_EXECUTE_TIMEOUT", raising=False)
    monkeypatch.delenv("LLM_INVOKE_TIMEOUT", raising=False)
    assert _resolve_agent_execute_timeout() == 300
    monkeypatch.setenv("LLM_INVOKE_TIMEOUT", "11")
    assert _resolve_agent_execute_timeout() == 11
    monkeypatch.setenv("AGENT_EXECUTE_TIMEOUT", "22")
    assert _resolve_agent_execute_timeout() == 22


def test_is_eventlet_environment_false_when_import_fails():
    import builtins

    real_import = builtins.__import__

    def _boom(name, *args, **kwargs):
        if name == "eventlet" or name.startswith("eventlet."):
            raise ImportError("missing eventlet")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", _boom):
        assert _is_eventlet_environment() is False


def test_cancel_all_tasks_cancels_pending():
    loop = MagicMock()
    task = MagicMock()
    with patch("apps.opspilot.services.chat_service.asyncio.all_tasks", return_value={task}):
        with patch("apps.opspilot.services.chat_service.asyncio.gather", return_value="done") as gather:
            _cancel_all_tasks(loop)
    task.cancel.assert_called_once()
    gather.assert_called_once()
    loop.run_until_complete.assert_called_once()
    with patch("apps.opspilot.services.chat_service.asyncio.all_tasks", return_value=set()):
        _cancel_all_tasks(loop)
