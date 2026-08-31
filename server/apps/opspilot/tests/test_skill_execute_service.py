"""SkillExecuteService：规则阈值、引用知识拼接与企业微信标题。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.opspilot.services.skill_execute_service import SkillExecuteService

pytestmark = pytest.mark.unit


def _skill(**extra):
    data = dict(
        skill_type=1,
        llm_model_id=3,
        skill_prompt="sys-prompt",
        enable_rag=True,
        enable_rag_knowledge_source=True,
        enable_rag_strict_mode=False,
        rag_score_threshold_map={"7": "0.8", "8": "0.6"},
        temperature=0.2,
        show_think=True,
        tools=[],
        team=[11],
        enable_km_route=False,
        km_llm_model=None,
        enable_suggest=False,
        enable_query_rewrite=False,
    )
    data.update(extra)
    return SimpleNamespace(**data)


def _bot(skill):
    return SimpleNamespace(id=42, llm_skills=SimpleNamespace(first=lambda: skill))


def test_get_rule_result_maps_threshold_and_prompt():
    skill = _skill()
    prompt, thresholds = SkillExecuteService.get_rule_result("web", skill, user=None, groups=[])
    assert prompt == "sys-prompt"
    assert thresholds == [
        {"knowledge_base": 7, "score": 0.8},
        {"knowledge_base": 8, "score": 0.6},
    ]


def test_format_enterprise_wechat_title_builds_preview_links(settings):
    settings.OPSPILOT_WEB_URL = "https://pilot.example/"
    titles = SkillExecuteService.format_enterprise_wechat_title(
        [{"knowledge_title": "手册", "knowledge_id": 19}]
    )
    assert titles == ["[手册](https://pilot.example/opspilot/knowledge/preview?id=19)"]


def test_execute_skill_appends_web_citations_and_skips_when_already_present():
    skill = _skill()
    bot = _bot(skill)
    user = SimpleNamespace(name="alice", user_id="u-1")
    chat = {
        "content": "答案正文",
        "citing_knowledge": [{"knowledge_title": "手册", "knowledge_id": 19}],
    }
    with (
        patch("apps.opspilot.services.skill_execute_service.get_user_info", return_value=(user, [])),
        patch("apps.opspilot.services.skill_execute_service.chat_service.chat", return_value=dict(chat)) as chat_fn,
    ):
        out = SkillExecuteService.execute_skill(bot, "chat", "你好", [{"role": "user"}], "sender-1", "web")
    assert out["content"] == "答案正文\n引用知识: 手册"
    params = chat_fn.call_args.args[0]
    assert params["username"] == "alice"
    assert params["user_id"] == "u-1"
    assert params["bot_id"] == 42
    assert params["skill_prompt"] == "sys-prompt"
    assert params["rag_score_threshold"] == [
        {"knowledge_base": 7, "score": 0.8},
        {"knowledge_base": 8, "score": 0.6},
    ]
    assert params["group"] == 11

    chat["content"] = "答案\n引用知识: 已有"
    with (
        patch("apps.opspilot.services.skill_execute_service.get_user_info", return_value=(user, [])),
        patch("apps.opspilot.services.skill_execute_service.chat_service.chat", return_value=dict(chat)),
    ):
        skipped = SkillExecuteService.execute_skill(bot, "chat", "hi", [], "s", "web")
    assert skipped["content"] == "答案\n引用知识: 已有"


def test_execute_skill_enterprise_wechat_uses_markdown_titles(settings):
    settings.OPSPILOT_WEB_URL = "https://pilot.example"
    skill = _skill()
    bot = _bot(skill)
    user = SimpleNamespace(name="bob", user_id="u-2")
    chat = {
        "content": "ok",
        "citing_knowledge": [{"knowledge_title": "手册", "knowledge_id": 19}],
    }
    with (
        patch("apps.opspilot.services.skill_execute_service.get_user_info", return_value=(user, [])),
        patch("apps.opspilot.services.skill_execute_service.chat_service.chat", return_value=dict(chat)),
    ):
        out = SkillExecuteService.execute_skill(bot, "chat", "hi", [], "s", "enterprise_wechat")
    assert out["content"] == "ok\n引用知识: [手册](https://pilot.example/opspilot/knowledge/preview?id=19)"


def test_execute_skill_without_rag_source_keeps_content():
    skill = _skill(enable_rag_knowledge_source=False)
    bot = _bot(skill)
    user = SimpleNamespace(name="carol", user_id="u-3")
    with (
        patch("apps.opspilot.services.skill_execute_service.get_user_info", return_value=(user, [])),
        patch(
            "apps.opspilot.services.skill_execute_service.chat_service.chat",
            return_value={"content": "plain", "citing_knowledge": [{"knowledge_title": "x", "knowledge_id": 1}]},
        ),
    ):
        out = SkillExecuteService.execute_skill(bot, "chat", "hi", [], "s", "web")
    assert out["content"] == "plain"
