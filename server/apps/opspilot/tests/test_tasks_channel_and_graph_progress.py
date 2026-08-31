"""渠道消息处理早退/重试，以及图谱任务进度更新。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Retry

from apps.opspilot import tasks
from apps.opspilot.models.knowledge_mgmt import KnowledgeTask

pytestmark = pytest.mark.django_db


def _run_inline(fn, *args, **kwargs):
    return fn(*args, **kwargs)


def test_update_graph_task_sets_progress_and_skips_missing():
    with patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline):
        assert tasks.update_graph_task(1, 4, 999999) is None
        task = KnowledgeTask.objects.create(task_name="graph-progress", created_by="u1", total_count=4)
        tasks.update_graph_task(3, 4, task.id)
    task.refresh_from_db()
    assert task.completed_count == 3
    assert task.train_progress == 75.0


def test_run_channel_message_marks_failed_when_bot_offline():
    handler_cls = MagicMock()
    handler = handler_cls.return_value
    celery_task = MagicMock()
    with (
        patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline),
        patch.object(tasks, "_get_bot_chat_flow", return_value=None),
    ):
        assert tasks._run_channel_message(celery_task, handler_cls, 9, "m-1", "hi", "u1", {"node_id": "n1"}, "微信") is None
    handler.mark_message_failed.assert_called_once_with("m-1")
    handler.async_process_and_reply.assert_not_called()
    celery_task.retry.assert_not_called()


def test_run_channel_message_success_delegates_to_handler():
    handler_cls = MagicMock()
    handler = handler_cls.return_value
    flow = SimpleNamespace(id=17)
    celery_task = MagicMock()
    config = {"node_id": "n1"}
    with (
        patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline),
        patch.object(tasks, "_get_bot_chat_flow", return_value=flow),
    ):
        tasks._run_channel_message(celery_task, handler_cls, 9, "m-2", "hello", "openid", config, "微信公众号")
    handler.async_process_and_reply.assert_called_once_with(flow, config, "hello", "openid", "m-2")
    handler.mark_message_failed.assert_not_called()
    celery_task.retry.assert_not_called()


def test_run_channel_message_retries_on_handler_error():
    handler_cls = MagicMock()
    handler = handler_cls.return_value
    handler.async_process_and_reply.side_effect = RuntimeError("boom")
    celery_task = MagicMock()
    celery_task.retry.side_effect = Retry()
    with (
        patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline),
        patch.object(tasks, "_get_bot_chat_flow", return_value=SimpleNamespace(id=1)),
        pytest.raises(Retry),
    ):
        tasks._run_channel_message(celery_task, handler_cls, 9, "m-3", "hi", "u1", {}, "微信")
    celery_task.retry.assert_called_once()
    assert isinstance(celery_task.retry.call_args.kwargs["exc"], RuntimeError)
    assert str(celery_task.retry.call_args.kwargs["exc"]) == "boom"


def test_process_dingtalk_message_offline_marks_failed_without_execute():
    handler = MagicMock()
    with (
        patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline),
        patch.object(tasks, "_get_bot_chat_flow", return_value=None),
        patch("apps.opspilot.services.dingtalk_chat_flow_utils.DingTalkChatFlowUtils", return_value=handler),
    ):
        assert tasks.process_dingtalk_message.run(3, "d-1", "hi", "u1", "http://hook", {"node_id": "n1"}) is None
    handler.mark_message_failed.assert_called_once_with("d-1")
    handler.execute_chatflow_with_message.assert_not_called()
    handler.send_message.assert_not_called()


def test_process_dingtalk_message_sends_markdown_and_completes():
    handler = MagicMock()
    handler.execute_chatflow_with_message.return_value = "reply-text"
    flow = SimpleNamespace(id=8)
    config = {"node_id": "n9"}
    with (
        patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline),
        patch.object(tasks, "_get_bot_chat_flow", return_value=flow),
        patch("apps.opspilot.services.dingtalk_chat_flow_utils.DingTalkChatFlowUtils", return_value=handler),
    ):
        tasks.process_dingtalk_message.run(3, "d-2", "ask", "u1", "http://hook", config)
    handler.execute_chatflow_with_message.assert_called_once_with(flow, "n9", "ask", "u1")
    handler.send_message.assert_called_once_with("http://hook", "markdown", {"title": "机器人回复", "text": "reply-text"})
    handler.mark_message_completed.assert_called_once_with("d-2")


def test_process_memory_write_cache_skips_empty_content():
    assert tasks.process_memory_write_cache(1, "t", "", "u", "domain.com") is None
