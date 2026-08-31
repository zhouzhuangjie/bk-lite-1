"""ChatFlowInitService._init_single_chatflow：缺目录/缺文件跳过，完整目录创建内置 Bot。"""
import json
from pathlib import Path

import pytest

from apps.opspilot.enum import BotTypeChoice
from apps.opspilot.models import Bot, BotWorkFlow, LLMSkill, SkillTools
from apps.opspilot.services.chatflow_init_service import ChatFlowInitService

pytestmark = pytest.mark.django_db


def test_init_single_skips_missing_dir_and_incomplete_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ChatFlowInitService, "CHATFLOW_DATA_DIR", tmp_path)
    svc = ChatFlowInitService()
    svc._init_single_chatflow({"id": "missing", "name": "X", "format_skill_name": "X-fmt"})
    assert LLMSkill.objects.count() == 0

    incomplete = tmp_path / "partial"
    incomplete.mkdir()
    (incomplete / "check.txt").write_text("check", encoding="utf-8")
    svc._init_single_chatflow({"id": "partial", "name": "P", "format_skill_name": "P-fmt"})
    assert LLMSkill.objects.count() == 0


def test_init_single_creates_builtin_skills_bot_and_rewrites_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(ChatFlowInitService, "CHATFLOW_DATA_DIR", tmp_path)
    SkillTools.objects.create(name="postgres", params={"kwargs": [{"key": "host"}]}, description="db", team=[1])
    flow_dir = tmp_path / "inspect"
    flow_dir.mkdir()
    (flow_dir / "check.txt").write_text("巡检提示", encoding="utf-8")
    (flow_dir / "format.txt").write_text("格式化提示", encoding="utf-8")
    workflow = {
        "nodes": [
            {
                "id": "a1",
                "type": "agents",
                "data": {"config": {"agentName": "巡检助手"}},
            },
            {
                "id": "a2",
                "type": "agents",
                "data": {"config": {"agentName": "巡检格式化"}},
            },
            {
                "id": "n1",
                "type": "notification",
                "data": {"config": {"notificationRecipients": ["ops"]}},
            },
        ]
    }
    (flow_dir / "workflow.json").write_text(json.dumps(workflow), encoding="utf-8")

    svc = ChatFlowInitService()
    config = {
        "id": "inspect",
        "name": "巡检助手",
        "format_skill_name": "巡检格式化",
        "description": "巡检描述",
        "tools": ["postgres", "missing-tool"],
    }
    svc._init_single_chatflow(config)

    main = LLMSkill.objects.get(name="巡检助手", is_builtin=True)
    fmt = LLMSkill.objects.get(name="巡检格式化", is_builtin=True)
    assert main.skill_prompt == "巡检提示"
    assert main.tools[0]["name"] == "postgres"
    assert fmt.skill_prompt == "格式化提示"
    bot = Bot.objects.get(name="巡检助手", is_builtin=True)
    assert bot.bot_type == BotTypeChoice.CHAT_FLOW
    flow = BotWorkFlow.objects.get(bot=bot)
    nodes = {n["id"]: n for n in flow.flow_json["nodes"]}
    assert nodes["a1"]["data"]["config"]["agent"] == main.id
    assert nodes["a2"]["data"]["config"]["agent"] == fmt.id
    assert nodes["n1"]["data"]["config"]["notificationRecipients"] == []

    svc._init_single_chatflow(config)
    assert LLMSkill.objects.filter(name="巡检助手", is_builtin=True).count() == 1
    assert Bot.objects.filter(name="巡检助手", is_builtin=True).count() == 1
