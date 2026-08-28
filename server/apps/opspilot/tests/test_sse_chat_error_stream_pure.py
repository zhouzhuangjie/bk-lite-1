"""SSE 错误流：错误事件以 data 行输出并以 [DONE] 结束。"""
import pytest

from apps.opspilot.utils import sse_chat

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_create_error_stream_response_emits_done():
    resp = sse_chat.create_error_stream_response("boom")
    chunks = []
    async for part in resp.streaming_content:
        chunks.append(part.decode() if isinstance(part, bytes) else part)
    text = "".join(chunks)
    assert "boom" in text
    assert "[DONE]" in text
    assert resp["Cache-Control"].startswith("no-cache")


@pytest.mark.asyncio
async def test_generate_stream_error_uses_openai_chunk_shape():
    resp = sse_chat.generate_stream_error("nope")
    chunks = []
    async for part in resp.streaming_content:
        chunks.append(part.decode() if isinstance(part, bytes) else part)
    assert "nope" in "".join(chunks)
    chunk = sse_chat._create_stream_chunk("hi", "skill-1", finish_reason="stop")
    assert chunk["choices"][0]["delta"]["content"] == "hi"
    assert chunk["id"] == "skill-1"
    err = sse_chat._create_error_chunk("bad", "skill-1")
    assert err["choices"][0]["finish_reason"] == "stop"
