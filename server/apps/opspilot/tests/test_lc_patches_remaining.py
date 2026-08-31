"""lc_patches：把 reasoning_content 从响应保留到请求。"""
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from apps.opspilot.metis.llm.chain import lc_patches

pytestmark = pytest.mark.unit


def test_convert_dict_to_message_keeps_reasoning_content(monkeypatch):
    msg = AIMessage(content="hi")
    monkeypatch.setattr(lc_patches, "_original_convert_dict_to_message", lambda *_a, **_k: msg)
    out = lc_patches._patched_convert_dict_to_message({"role": "assistant", "reasoning_content": "think"})
    assert out.additional_kwargs["reasoning_content"] == "think"

    msg2 = AIMessage(content="hi")
    monkeypatch.setattr(lc_patches, "_original_convert_dict_to_message", lambda *_a, **_k: msg2)
    out2 = lc_patches._patched_convert_dict_to_message({"role": "assistant", "reasoning": "qwen-think"})
    assert out2.additional_kwargs["reasoning_content"] == "qwen-think"


def test_create_chat_result_reads_model_extra(monkeypatch):
    class BM:
        pass

    class ChoiceMsg:
        reasoning_content = None
        reasoning = None
        model_extra = {"reasoning": "from-extra"}

    class RawResp(BM):
        choices = [SimpleNamespace(message=ChoiceMsg())]

    gen_msg = AIMessage(content="ans")
    result = SimpleNamespace(generations=[SimpleNamespace(message=gen_msg)])
    monkeypatch.setattr(lc_patches.openai, "BaseModel", BM)
    monkeypatch.setattr(lc_patches, "_original_create_chat_result", lambda self, resp, info=None: result)
    out = lc_patches._patched_create_chat_result(object(), RawResp())
    assert out.generations[0].message.additional_kwargs["reasoning_content"] == "from-extra"


def test_convert_delta_chunk_keeps_reasoning(monkeypatch):
    chunk = AIMessageChunk(content="x")
    monkeypatch.setattr(lc_patches, "_original_convert_delta_to_message_chunk", lambda *_a, **_k: chunk)
    out = lc_patches._patched_convert_delta_to_message_chunk({"reasoning_content": "delta"}, AIMessageChunk)
    assert out.additional_kwargs["reasoning_content"] == "delta"


def test_convert_message_to_dict_injects_reasoning(monkeypatch):
    monkeypatch.setattr(
        lc_patches,
        "_original_convert_message_to_dict",
        lambda message, *a, **k: {"role": "assistant", "content": message.content},
    )
    msg = AIMessage(content="ans", additional_kwargs={"reasoning_content": "think-back"})
    out = lc_patches._patched_convert_message_to_dict(msg)
    assert out["reasoning_content"] == "think-back"
    human = HumanMessage(content="q")
    assert "reasoning_content" not in lc_patches._patched_convert_message_to_dict(human)
