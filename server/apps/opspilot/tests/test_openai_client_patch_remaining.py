"""Graphiti OpenAI 客户端补丁：序列化降级、默认字段、ImportError。"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from apps.opspilot.metis.llm.rag.graph_rag.graphiti import openai_client_patch as p

pytestmark = pytest.mark.unit


class DumpV1(BaseModel):
    name: str = Field(default="")

    def model_dump_json(self, *args, **kwargs):
        if "ensure_ascii" in kwargs:
            raise TypeError("ensure_ascii not supported")
        return '{"name":"v1"}'


class DumpAttr(BaseModel):
    name: str = Field(default="x")

    def model_dump_json(self, *args, **kwargs):
        raise AttributeError("no json")

    def dict(self):
        return {"name": "from-dict"}


class DefaultsOut(BaseModel):
    tags: list[str] = Field(default_factory=list)
    name: str = ""
    score: int = 0
    ratio: float = 0.0
    ok: bool = False
    extra: dict = Field(default_factory=dict)


class ExtractedEntities(BaseModel):
    extracted_entities: list = Field(default_factory=list)

    def __init__(self, **kwargs):
        raise RuntimeError("cannot construct")


@pytest.mark.asyncio
async def test_structured_completion_falls_back_when_ensure_ascii_unsupported():
    client = SimpleNamespace(client=SimpleNamespace(base_url="http://llm", api_key="k"))
    parser = MagicMock()
    parser.parse_with_structured_output = AsyncMock(return_value=DumpV1(name="ok"))
    with patch.object(p, "ChatOpenAI"), patch.object(p, "StructuredOutputParser", return_value=parser):
        resp = await p.patched_create_structured_completion(
            client, model="gpt", messages=[{"role": "user", "content": "hi"}], temperature=0, max_tokens=8, response_model=DumpV1
        )
    assert resp.output_text == '{"name":"v1"}'


@pytest.mark.asyncio
async def test_structured_completion_serializes_via_dict_when_dump_json_missing():
    client = SimpleNamespace(client=SimpleNamespace(base_url=None, api_key=None))
    parser = MagicMock()
    parser.parse_with_structured_output = AsyncMock(return_value=DumpAttr())
    with patch.object(p, "ChatOpenAI"), patch.object(p, "StructuredOutputParser", return_value=parser):
        resp = await p.patched_create_structured_completion(
            client, model="gpt", messages=[{"role": "assistant", "content": "prev"}], temperature=0, max_tokens=8, response_model=DumpAttr
        )
    assert resp.output_text == '{"name":"x"}'


@pytest.mark.asyncio
async def test_parse_failure_builds_typed_defaults():
    client = SimpleNamespace(client=SimpleNamespace(base_url=None, api_key=None))
    parser = MagicMock()
    parser.parse_with_structured_output = AsyncMock(side_effect=RuntimeError("parse fail"))
    with patch.object(p, "ChatOpenAI"), patch.object(p, "StructuredOutputParser", return_value=parser):
        resp = await p.patched_create_structured_completion(
            client, model="gpt", messages=[{"role": "user", "content": "x"}], temperature=0, max_tokens=8, response_model=DefaultsOut
        )
    data = json.loads(resp.output_text)
    assert data["tags"] == []
    assert data["name"] == ""
    assert data["score"] == 0
    assert data["ratio"] == 0.0
    assert data["ok"] is False
    assert data["extra"] == {}


@pytest.mark.asyncio
async def test_default_instance_failure_uses_extracted_entities_fallback():
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
            response_model=ExtractedEntities,
        )
    assert resp.output_text == '{"extracted_entities": []}'


def test_apply_patch_reraises_import_error(monkeypatch):
    import builtins

    real = builtins.__import__

    def _imp(name, *args, **kwargs):
        if name.startswith("graphiti_core"):
            raise ImportError("no graphiti")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _imp)
    with pytest.raises(ImportError, match="no graphiti"):
        p.apply_openai_client_patch()


def test_apply_patch_reraises_when_original_method_missing():
    class Dummy:
        pass

    fake = MagicMock()
    fake.OpenAIClient = Dummy
    import sys

    sys.modules["graphiti_core.llm_client.openai_client"] = fake
    with pytest.raises(AttributeError):
        p.apply_openai_client_patch()


def test_remove_patch_warns_when_original_missing():
    class Dummy:
        _create_structured_completion = staticmethod(lambda: "orig")

    fake = MagicMock()
    fake.OpenAIClient = Dummy
    import sys

    sys.modules["graphiti_core.llm_client.openai_client"] = fake
    p.remove_openai_client_patch()
    assert Dummy._create_structured_completion() == "orig"


def test_remove_patch_reraises_import_error(monkeypatch):
    import builtins

    real = builtins.__import__

    def _imp(name, *args, **kwargs):
        if name.startswith("graphiti_core"):
            raise ImportError("no graphiti")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _imp)
    with pytest.raises(ImportError, match="no graphiti"):
        p.remove_openai_client_patch()
