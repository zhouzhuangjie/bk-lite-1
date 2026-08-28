"""opspilot.tasks：图谱创建/重建失败写 failed；ChatFlow 周期任务校验 Bot 与工作流。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot import tasks
from apps.opspilot.models import Bot, BotWorkFlow

pytestmark = pytest.mark.django_db


def _run_inline(fn, *args, **kwargs):
    return fn(*args, **kwargs)


def test_create_graph_success_and_failure():
    instance = MagicMock()
    instance.id = 7
    instance.status = "pending"
    with (
        patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline),
        patch("apps.opspilot.tasks.KnowledgeGraph.objects.get", return_value=instance),
        patch("apps.opspilot.tasks.GraphUtils.create_graph", return_value={"result": False, "message": "boom"}),
    ):
        tasks.create_graph(7)
    assert instance.status == "failed"

    instance.status = "pending"
    with (
        patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline),
        patch("apps.opspilot.tasks.KnowledgeGraph.objects.get", return_value=instance),
        patch("apps.opspilot.tasks.GraphUtils.create_graph", return_value={"result": True}),
    ):
        tasks.create_graph(7)
    assert instance.status == "completed"


def test_rebuild_graph_community_failure_and_success():
    instance = MagicMock()
    instance.id = 3
    with (
        patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline),
        patch("apps.opspilot.tasks.KnowledgeGraph.objects.get", return_value=instance),
        patch("apps.opspilot.tasks.GraphUtils.rebuild_graph_community", return_value={"result": False}),
    ):
        tasks.rebuild_graph_community_by_instance(3)
    assert instance.status == "failed"
    with (
        patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline),
        patch("apps.opspilot.tasks.KnowledgeGraph.objects.get", return_value=instance),
        patch("apps.opspilot.tasks.GraphUtils.rebuild_graph_community", return_value={"result": True}),
    ):
        tasks.rebuild_graph_community_by_instance(3)
    assert instance.status == "completed"


def test_update_graph_success():
    instance = MagicMock()
    instance.id = 4
    with (
        patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline),
        patch("apps.opspilot.tasks.KnowledgeGraph.objects.get", return_value=instance),
        patch("apps.opspilot.tasks.GraphUtils.update_graph", return_value={"result": True}),
    ):
        tasks.update_graph(4, ["old"])
    assert instance.status == "completed"


def test_chat_flow_celery_task_requires_online_bot_and_workflow():
    with patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline):
        tasks.chat_flow_celery_task(999999, "n1", "hi")

    bot = Bot.objects.create(name="flow-bot", team=[1], online=False)
    with patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline):
        tasks.chat_flow_celery_task(bot.id, "n1", "hi")

    bot.online = True
    bot.save()
    with patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline):
        tasks.chat_flow_celery_task(bot.id, "n1", "hi")

    BotWorkFlow.objects.create(bot=bot, flow_json={"nodes": []})
    engine = MagicMock()
    engine.execute.return_value = {"content": "ok"}
    with (
        patch.object(tasks, "_run_in_native_thread", side_effect=_run_inline),
        patch("apps.opspilot.tasks.create_chat_flow_engine", return_value=engine),
    ):
        tasks.chat_flow_celery_task(bot.id, "n1", "hi")
    engine.execute.assert_called_once()
    assert engine.execute.call_args.args[0]["last_message"] == "hi"
