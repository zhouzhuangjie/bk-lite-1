"""Graphiti OpenAI 客户端补丁：结构化输出成功与默认值降级。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from apps.opspilot.metis.llm.rag.graph_rag.graphiti import openai_client_patch as p

pytestmark = pytest.mark.unit


class SampleOut(BaseModel):
    name: str = Field(default="")
    score: int = Field(default=0)


@pytest.mark.asyncio
async def test_patched_structured_completion_serializes_model():
    client = SimpleNamespace(client=SimpleNamespace(base_url="http://llm", api_key="k"))
    parsed = SampleOut(name="ok", score=3)
    parser = MagicMock()
    parser.parse_with_structured_output = AsyncMock(return_value=parsed)
    with patch.object(p, "ChatOpenAI"), patch.object(p, "StructuredOutputParser", return_value=parser):
        resp = await p.patched_create_structured_completion(
            client,
            model="gpt",
            messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}, {"role": "assistant", "content": "prev"}],
            temperature=0,
            max_tokens=16,
            response_model=SampleOut,
        )
    assert isinstance(resp, p.MockResponse)
    assert '"name"' in resp.output_text
    assert "ok" in resp.output_text


@pytest.mark.asyncio
async def test_patched_structured_completion_falls_back_to_defaults():
    client = SimpleNamespace(client=SimpleNamespace(base_url=None, api_key=None))
    parser = MagicMock()
    parser.parse_with_structured_output = AsyncMock(side_effect=RuntimeError("parse fail"))
    with patch.object(p, "ChatOpenAI"), patch.object(p, "StructuredOutputParser", return_value=parser):
        resp = await p.patched_create_structured_completion(
            client,
            model="gpt",
            messages=[{"role": "user", "content": "x"}],
            temperature=0,
            max_tokens=8,
            response_model=SampleOut,
        )
    assert '"name": ""' in resp.output_text or '"name":""' in resp.output_text.replace(" ", "")


def test_apply_and_remove_patch_swaps_method():
    class Dummy:
        @staticmethod
        def _create_structured_completion():
            return "orig"

    fake = MagicMock()
    fake.OpenAIClient = Dummy
    import sys

    sys.modules["graphiti_core.llm_client.openai_client"] = fake
    p.apply_openai_client_patch()
    assert Dummy._create_structured_completion is p.patched_create_structured_completion
    p.remove_openai_client_patch()
    assert Dummy._create_structured_completion() == "orig"
