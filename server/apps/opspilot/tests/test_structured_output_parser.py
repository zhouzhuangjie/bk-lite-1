"""StructuredOutputParser：Qwen 关闭 thinking，解析成功与空响应回落默认模型。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field

from apps.opspilot.metis.llm.common.structured_output_parser import StructuredOutputParser

pytestmark = pytest.mark.unit


class _Item(BaseModel):
    name: str = Field(default="fallback")


def test_qwen_disables_thinking_and_parses_json():
    llm = SimpleNamespace(
        model_name="Qwen2-7B",
        extra_body=None,
        openai_api_key=SimpleNamespace(get_secret_value=lambda: "sk"),
        openai_api_base="http://llm.local",
        temperature=0.1,
    )
    parser = StructuredOutputParser(llm)
    assert llm.extra_body["enable_thinking"] is False

    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        SimpleNamespace(message=SimpleNamespace(content='{"name": "parsed"}'))
    ]
    parser._independent_llm = client
    result = asyncio.run(parser.parse_with_structured_output("extract name", _Item))
    assert result.name == "parsed"
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "Qwen2-7B"
    assert kwargs["extra_body"]["enable_thinking"] is False
    assert "extract name" in kwargs["messages"][0]["content"]


def test_empty_response_returns_default_model():
    llm = SimpleNamespace(model="gpt-4", extra_body=None, openai_api_key=None, openai_api_base="")
    parser = StructuredOutputParser(llm)
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        SimpleNamespace(message=SimpleNamespace(content="   "))
    ]
    parser._independent_llm = client
    result = asyncio.run(parser.parse_with_structured_output("x", _Item))
    assert result.name == "fallback"
