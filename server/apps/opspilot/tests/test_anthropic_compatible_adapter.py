"""Anthropic 兼容适配器：消息载荷组装、tool_choice 归一化、连接校验与运行时生成。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from apps.opspilot.metis.llm.common.anthropic_compatible_adapter import (
    ANTHROPIC_INVALID_API_KEY_ERROR,
    AnthropicCompatibleAdapter,
    AnthropicCompatibleChatClient,
    _build_ai_message,
    _normalize_tool_choice_to_object,
    _schema_to_parameters,
    build_anthropic_headers,
    build_messages_payload,
    build_tool_definitions,
    normalize_messages_url,
)

pytestmark = pytest.mark.unit


def test_normalize_url_and_headers():
    assert normalize_messages_url("") == "https://api.anthropic.com/v1/messages"
    assert normalize_messages_url("https://example.com/v1/") == "https://example.com/v1/v1/messages"
    headers = build_anthropic_headers("sk-test")
    assert headers["x-api-key"] == "sk-test"
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["content-type"] == "application/json"


def test_schema_to_parameters_and_tool_definitions():
    assert _schema_to_parameters(None) == {"type": "object", "properties": {}}
    schema_obj = SimpleNamespace(model_json_schema=lambda: {"type": "object", "properties": {"q": {"type": "string"}}})
    assert _schema_to_parameters(schema_obj)["properties"]["q"]["type"] == "string"
    legacy = SimpleNamespace(schema=lambda: {"type": "object", "properties": {"n": {"type": "integer"}}})
    assert _schema_to_parameters(legacy)["properties"]["n"]["type"] == "integer"
    assert _schema_to_parameters(object()) == {"type": "object", "properties": {}}

    tool = SimpleNamespace(name="search", description="find", args_schema=schema_obj)
    defs = build_tool_definitions([tool])
    assert defs == [
        {
            "name": "search",
            "description": "find",
            "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
    ]
    assert build_tool_definitions(None) == []


def test_build_messages_payload_maps_system_tool_and_assistant_calls():
    messages = [
        SimpleNamespace(type="system", content="you are helpful"),
        SimpleNamespace(type="user", content="hi"),
        SimpleNamespace(
            type="assistant",
            content="calling",
            tool_calls=[{"id": "call-1", "name": "search", "args": {"q": "bk"}}],
        ),
        SimpleNamespace(type="tool", content="hit", tool_call_id="call-1"),
        SimpleNamespace(type="ai", content="done"),
    ]
    tool = SimpleNamespace(name="search", description="find", args_schema=None)
    payload = build_messages_payload(
        model="claude-3",
        messages=messages,
        temperature=0.2,
        max_tokens=128,
        tools=[tool],
        tool_choice="auto",
    )
    assert payload["model"] == "claude-3"
    assert payload["system"] == "you are helpful"
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 128
    assert payload["tool_choice"] == {"type": "auto"}
    assert payload["tools"][0]["name"] == "search"
    assert payload["messages"][0] == {"role": "user", "content": "hi"}
    assistant = payload["messages"][1]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == {"type": "text", "text": "calling"}
    assert assistant["content"][1] == {
        "type": "tool_use",
        "id": "call-1",
        "name": "search",
        "input": {"q": "bk"},
    }
    tool_msg = payload["messages"][2]
    assert tool_msg["role"] == "user"
    assert tool_msg["content"] == [
        {"type": "tool_result", "tool_use_id": "call-1", "content": "hit"}
    ]
    assert payload["messages"][3] == {
        "role": "assistant",
        "content": [{"type": "text", "text": "done"}],
    }


def test_normalize_tool_choice_variants():
    assert _normalize_tool_choice_to_object({"type": "auto"}) == {"type": "auto"}
    assert _normalize_tool_choice_to_object("required") == {"type": "required"}
    assert _normalize_tool_choice_to_object("weather") == {"type": "tool", "name": "weather"}
    payload = build_messages_payload(
        model="m",
        messages=[SimpleNamespace(type="user", content="x")],
        temperature=0,
        tool_choice="none",
    )
    assert "tool_choice" not in payload


def test_build_ai_message_splits_text_and_tool_use():
    msg = _build_ai_message(
        {
            "content": [
                {"type": "text", "text": "hello "},
                {"type": "text", "text": "world"},
                {"type": "tool_use", "name": "search", "input": {"q": "a"}, "id": "t1"},
            ]
        }
    )
    assert isinstance(msg, AIMessage)
    assert msg.content == "hello world"
    assert msg.tool_calls == [{"name": "search", "args": {"q": "a"}, "id": "t1", "type": "tool_call"}]
    empty = _build_ai_message({"content": []})
    assert empty.content == ""
    assert empty.tool_calls == []


def test_validate_connection_raises_on_auth_and_http_errors():
    with patch(
        "apps.opspilot.metis.llm.common.anthropic_compatible_adapter.safe_post_llm_endpoint"
    ) as post:
        post.return_value = SimpleNamespace(status_code=401, text="unauthorized")
        with pytest.raises(ValueError, match=ANTHROPIC_INVALID_API_KEY_ERROR):
            AnthropicCompatibleAdapter.validate_minimal_connection("", "bad-key", "m")
        post.return_value = SimpleNamespace(status_code=500, text="boom" * 80)
        with pytest.raises(ValueError, match="API 连接失败"):
            AnthropicCompatibleAdapter.validate_minimal_connection("https://x", "k", "m")


def test_chat_client_generate_and_bind_tools():
    client = AnthropicCompatibleChatClient(
        model="claude-3",
        api_key="sk",
        api_base="https://api.example.com",
        temperature=0.1,
    )
    assert client._llm_type == "anthropic-compatible"
    bound = client.bind_tools([SimpleNamespace(name="t", description="", args_schema=None)], tool_choice="auto")
    assert bound.bound_tools[0].name == "t"
    assert bound.bound_tool_choice == "auto"

    fake_resp = SimpleNamespace(
        status_code=200,
        json=lambda: {"content": [{"type": "text", "text": "ok"}]},
        text="",
    )
    with patch(
        "apps.opspilot.metis.llm.common.anthropic_compatible_adapter.safe_post_llm_endpoint",
        return_value=fake_resp,
    ) as post:
        result = bound._generate([SimpleNamespace(type="user", content="hi")])
    assert result.generations[0].message.content == "ok"
    sent = post.call_args.kwargs["json"]
    assert sent["model"] == "claude-3"
    assert sent["messages"][0]["content"] == "hi"
    assert sent["tool_choice"] == {"type": "auto"}
