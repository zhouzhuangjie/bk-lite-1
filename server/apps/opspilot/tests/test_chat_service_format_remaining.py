"""ChatService：引用知识组装、知识工具 extra_config、附件强制提示与 thread_id。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.opspilot.enum import SkillTypeChoices
from apps.opspilot.services.builtin_tools import BUILTIN_ATTACHMENT_FILE_TOOL_NAME
from apps.opspilot.services.chat_service import ChatService

pytestmark = pytest.mark.unit


def _llm():
    vendor = SimpleNamespace(vendor_type="openai")
    return SimpleNamespace(
        openai_api_base="https://llm.example/v1",
        openai_api_key="k",
        model_name="gpt-4o",
        protocol_type="openai",
        vendor_id=1,
        vendor=vendor,
    )


def _base_kwargs(**extra):
    data = {
        "user_message": "hello",
        "chat_history": [],
        "skill_prompt": "sys",
        "skill_params": [],
        "temperature": 0.1,
        "user_id": 8,
        "enable_rag": False,
        "enable_rag_knowledge_source": False,
        "skill_type": 1,
        "locale": "zh",
        "tools": [],
        "llm_model": 3,
    }
    data.update(extra)
    return data


def test_chat_builds_citing_knowledge_from_title_map():
    with patch.object(
        ChatService,
        "invoke_chat",
        return_value=(
            {"message": "答案"},
            {"k1": {"name": "手册", "knowledge_base_id": 7, "knowledge_source_type": "file"}},
            {"k1": ["hit-a", "hit-b"]},
        ),
    ):
        out = ChatService.chat(_base_kwargs(enable_rag_knowledge_source=True))
    assert out["content"] == "答案"
    assert out["citing_knowledge"] == [
        {
            "knowledge_title": "手册",
            "knowledge_id": "k1",
            "knowledge_base_id": 7,
            "result": ["hit-a", "hit-b"],
            "knowledge_source_type": "file",
            "citing_num": 2,
        }
    ]

    with patch.object(ChatService, "invoke_chat", return_value=({"message": "plain"}, {}, {})):
        skipped = ChatService.chat(_base_kwargs(enable_rag_knowledge_source=False))
    assert skipped == {"content": "plain", "citing_knowledge": []}


def test_format_knowledge_tool_skips_tools_and_copies_ids():
    llm = _llm()
    with (
        patch("apps.opspilot.services.chat_service.history_service.process_user_message_and_images", return_value=("hello", [])),
        patch("apps.opspilot.services.chat_service.history_service.process_chat_history", return_value=[]),
        patch("apps.opspilot.services.chat_service.resolve_skill_params", return_value="sys"),
        patch.object(ChatService, "_process_tools_and_extra_config") as tools,
    ):
        chat_kwargs, doc_map, title_map = ChatService.format_chat_server_kwargs(
            _base_kwargs(
                skill_type=SkillTypeChoices.KNOWLEDGE_TOOL,
                thread_id="thread-9",
                attachment_id="att-1",
                node_id="n1",
                trigger_type="cron",
                enable_rag_knowledge_source=True,
                enable_rag_strict_mode=True,
                matched_skill_packages=["pkg"],
                skill_package_capabilities=["cap"],
                skill_package_reports={"r": 1},
                skill_package_workflows={"w": 2},
                browser_use_force_task=True,
            ),
            llm,
        )
    tools.assert_not_called()
    assert doc_map == {} and title_map == {}
    extra = chat_kwargs["extra_config"]
    assert extra["enable_rag_source"] is True
    assert extra["enable_rag_strict_mode"] is True
    assert extra["attachment_id"] == "att-1"
    assert extra["node_id"] == "n1"
    assert extra["trigger_type"] == "cron"
    assert extra["matched_skill_packages"] == ["pkg"]
    assert extra["skill_package_capabilities"] == ["cap"]
    assert extra["browser_use_force_task"] is True
    assert extra["browser_use_user_message"] == "hello"
    assert chat_kwargs["thread_id"] == "thread-9"
    assert chat_kwargs["execution_id"] == "thread-9"


def test_format_injects_attachment_override_and_uses_execution_id_as_thread():
    llm = _llm()
    with (
        patch("apps.opspilot.services.chat_service.history_service.process_user_message_and_images", return_value=("hello", [])),
        patch("apps.opspilot.services.chat_service.history_service.process_chat_history", return_value=[]),
        patch("apps.opspilot.services.chat_service.resolve_skill_params", return_value="sys"),
        patch("apps.opspilot.services.chat_service.SkillTools.objects.filter", return_value=[]),
        patch(
            "apps.opspilot.services.chat_service.build_builtin_attachment_file_runtime_tool",
            return_value={"url": "langchain:attachment_file", "extra_tools_prompt": "gen"},
        ),
    ):
        chat_kwargs, _, _ = ChatService.format_chat_server_kwargs(
            _base_kwargs(
                execution_id="exec-22",
                tools=[{"name": BUILTIN_ATTACHMENT_FILE_TOOL_NAME, "kwargs": [{"key": "filename", "value": "a.md"}]}],
            ),
            llm,
        )
    assert chat_kwargs["thread_id"] == "exec-22"
    assert chat_kwargs["execution_id"] == "exec-22"
    assert "附件生成强制规则" in chat_kwargs["system_message_prompt"]
    assert any(item.get("url") == "langchain:attachment_file" for item in chat_kwargs["tools_servers"])
