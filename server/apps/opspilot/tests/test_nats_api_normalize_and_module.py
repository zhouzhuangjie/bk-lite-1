"""OpsPilot NATS：触发入参规范化、模块列表/分页、缺 workflow、对话引用知识。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.opspilot.models import Bot, BotConversationHistory, BotWorkFlow, ChannelUser, LLMSkill
from apps.opspilot.nats_api import (
    _normalize_nats_trigger_input,
    consume_bot_event,
    get_opspilot_module_data,
    get_opspilot_module_list,
    trigger_workflow_by_nats,
)

pytestmark = pytest.mark.django_db


def test_normalize_nats_trigger_input_rejects_invalid_fields():
    assert _normalize_nats_trigger_input("", 1, ["u"], 1, "n1")[1] == {
        "result": False,
        "message": "message is required",
    }
    assert _normalize_nats_trigger_input("  ", 1, ["u"], 1, "n1")[1]["message"] == "message is required"
    assert _normalize_nats_trigger_input("hi", [1, 2], ["u"], 1, "n1")[1] == {
        "result": False,
        "message": "team must be a single team id",
    }
    assert _normalize_nats_trigger_input("hi", "abc", ["u"], 1, "n1")[1] == {
        "result": False,
        "message": "team must be a single integer team id",
    }
    assert _normalize_nats_trigger_input("hi", 1, "u1", 1, "n1")[1] == {
        "result": False,
        "message": "user_ids must be a list",
    }
    assert _normalize_nats_trigger_input("hi", 1, ["u"], "x", "n1")[1] == {
        "result": False,
        "message": "bot_id must be an integer",
    }
    assert _normalize_nats_trigger_input("hi", 1, ["u"], 1, "")[1] == {
        "result": False,
        "message": "node_id is required",
    }
    assert _normalize_nats_trigger_input("hi", 1, ["u"], 1, None)[1]["message"] == "node_id is required"

    ok, err = _normalize_nats_trigger_input("  hello  ", ["7"], [None, " a ", ""], "9", " node-1 ")
    assert err is None
    assert ok == {
        "message": "hello",
        "team": 7,
        "user_ids": ["a"],
        "bot_id": 9,
        "node_id": "node-1",
    }


def test_get_opspilot_module_list_and_unknown_module():
    modules = get_opspilot_module_list()
    assert modules[0] == {"name": "bot", "display_name": "Studio"}
    provider = [m for m in modules if m["name"] == "provider"][0]
    assert [c["name"] for c in provider["children"]] == [
        "llm_model",
        "ocr_model",
        "embed_model",
        "rerank_model",
    ]
    assert get_opspilot_module_data("unknown", None, 1, 10, 1) == {
        "result": False,
        "message": "Unknown module: unknown",
    }
    assert get_opspilot_module_data("provider", "bad", 1, 10, 1) == {
        "result": False,
        "message": "Unknown child_module: bad",
    }


def test_get_opspilot_module_data_pages_team_scoped_items():
    Bot.objects.create(name="in-team", team=[3])
    Bot.objects.create(name="other-team", team=[9])
    LLMSkill.objects.create(name="skill-in", team=[3])
    out = get_opspilot_module_data("bot", None, 1, 10, 3)
    assert out["count"] == 1
    assert out["items"] == [{"id": Bot.objects.get(name="in-team").id, "name": "in-team"}]
    skill_out = get_opspilot_module_data("skill", None, 1, 10, 3)
    assert skill_out["count"] == 1
    assert skill_out["items"][0]["name"] == "skill-in"


def test_trigger_workflow_by_nats_missing_workflow_and_engine_success():
    assert trigger_workflow_by_nats("", 1, ["u"], 1, "n1") == {
        "result": False,
        "message": "message is required",
    }
    bot = Bot.objects.create(name="nats-bot", team=[1])
    assert trigger_workflow_by_nats("hello", 1, ["u1"], bot.id, "start") == {
        "result": False,
        "message": "Bot workflow not found",
    }
    BotWorkFlow.objects.create(bot=bot, flow_json={}, web_json={})
    engine = SimpleNamespace(execution_id="exec-1", execute=lambda data: {"success": True, "echo": data["message"]})
    with patch("apps.opspilot.nats_api.create_chat_flow_engine", return_value=engine) as create:
        out = trigger_workflow_by_nats("hello", 1, ["u1", None], bot.id, "start")
    create.assert_called_once()
    assert create.call_args.args[1] == "start"
    assert create.call_args.kwargs["entry_type"] == "nats"
    assert out == {
        "result": True,
        "data": {"success": True, "echo": "hello"},
        "entry_type": "nats",
        "execution_id": "exec-1",
    }


def test_consume_bot_event_writes_citing_knowledge_from_metadata():
    bot = Bot.objects.create(name="hist-bot", team=[1], created_by="admin", domain="domain.com")
    channel_user = ChannelUser.objects.create(user_id="wx-1", name="wx", channel_type="web")
    with patch("apps.opspilot.nats_api.get_user_info", return_value=(channel_user, True)):
        out = consume_bot_event(
            {
                "text": "问一下",
                "sender_id": "wx-1",
                "timestamp": 1700000000,
                "event": "user",
                "input_channel": "web",
                "bot_id": bot.id,
                "citing_knowledge": [],
                "metadata": {"other_data": {"citing_knowledge": [{"doc": "a\u0000b"}]}},
            }
        )
    assert out == {"result": True}
    hist = BotConversationHistory.objects.get(bot_id=bot.id)
    assert hist.conversation == "问一下"
    assert hist.conversation_role == "user"
    assert hist.channel_user_id == channel_user.id
    assert hist.citing_knowledge == [{"doc": "a b"}]

    missing_channel = consume_bot_event(
        {"text": "hi", "sender_id": "wx-1", "timestamp": 1, "event": "user", "bot_id": bot.id}
    )
    assert missing_channel == {"result": True}
