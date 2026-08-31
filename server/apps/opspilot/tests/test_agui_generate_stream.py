"""AGUI：pre_think_candidate 状态机与 _generate_agui_stream 流式分支。"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from apps.opspilot.utils.agui_chat import (
    _generate_agui_stream,
    _handle_agui_data_event,
    _init_agui_stream_state,
    stream_agui_chat,
)

pytestmark = pytest.mark.unit


def _payloads(lines):
    out = []
    for line in lines:
        if not line:
            continue
        assert line.startswith("data: ")
        out.append(json.loads(line[len("data: ") :].strip()))
    return out


class TestPreThinkCandidate:
    def test_bare_think_close_tag_is_dropped(self):
        state = _init_agui_stream_state()
        start, _ = _handle_agui_data_event({"type": "TEXT_MESSAGE_START", "message_id": "m1"}, state, True, True)
        assert json.loads(start[6:].strip())["type"] == "TEXT_MESSAGE_START"
        assert state["pending_phase"] == "pre_think_candidate"
        output, immediate = _handle_agui_data_event(
            {"type": "TEXT_MESSAGE_CONTENT", "message_id": "m1", "delta": "</think>"},
            state,
            True,
            True,
        )
        assert output == ""
        assert immediate == []
        assert state["pending_content_events"] == []

    def test_implicit_thinking_prefix_is_buffered_until_real_answer(self):
        state = _init_agui_stream_state()
        _handle_agui_data_event({"type": "TEXT_MESSAGE_START", "message_id": "m1"}, state, True, True)
        out1, _ = _handle_agui_data_event(
            {"type": "TEXT_MESSAGE_CONTENT", "message_id": "m1", "delta": "th"},
            state,
            True,
            True,
        )
        assert out1 == ""
        assert state["pending_phase"] == "pre_think_candidate"
        out2, immediate = _handle_agui_data_event(
            {"type": "TEXT_MESSAGE_CONTENT", "message_id": "m1", "delta": "最终答案是 42"},
            state,
            True,
            True,
        )
        assert state["pending_phase"] is None
        payloads = _payloads(immediate + ([out2] if out2 else []))
        deltas = "".join(p.get("delta", "") for p in payloads if p.get("type") == "TEXT_MESSAGE_CONTENT")
        assert "最终答案是 42" in deltas

    def test_think_close_inside_implicit_prefix_flushes_as_think_split(self):
        state = _init_agui_stream_state()
        _handle_agui_data_event({"type": "TEXT_MESSAGE_START", "message_id": "m1"}, state, True, True)
        output, immediate = _handle_agui_data_event(
            {"type": "TEXT_MESSAGE_CONTENT", "message_id": "m1", "delta": "thinking</think>最终答案"},
            state,
            True,
            True,
        )
        lines = immediate + ([output] if output else [])
        assert lines
        payloads = _payloads(lines)
        thinking = [p for p in payloads if p.get("type") == "THINKING"]
        content = [p for p in payloads if p.get("type") == "TEXT_MESSAGE_CONTENT"]
        assert [p["delta"] for p in thinking] == ["thinking"]
        assert [p["delta"] for p in content] == ["最终答案"]


class TestGenerateAguiStream:
    def _request(self, model="gpt-4o"):
        return SimpleNamespace(
            model=model,
            thread_id="thread-1",
            typed_extra_config=lambda: SimpleNamespace(execution_id="exec-agui"),
        )

    def _collect(self, params, graph, **kwargs):
        async def _run():
            chunks = []
            async for line in _generate_agui_stream(
                params,
                "skill-a",
                "chat",
                kwargs.get("show_think", True),
                kwargs.get("final_stats", {"content": []}),
                {},
                "10.0.0.1",
                "hello",
                12,
                None,
            ):
                chunks.append(line)
            return chunks

        def fake_sync_to_async(fn, thread_sensitive=True):
            async def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)

            return wrapper

        with (
            patch("apps.opspilot.utils.agui_chat.sync_to_async", side_effect=fake_sync_to_async),
            patch("apps.opspilot.utils.agui_chat._prepare_agui_chat_kwargs", return_value={"ok": True}),
            patch("apps.opspilot.utils.agui_chat.create_agent_instance", return_value=(graph, self._request())),
            patch("apps.opspilot.utils.agui_chat.is_interrupt_requested_async", new=kwargs.get("interrupt", AsyncMock(return_value=False))),
            patch("apps.opspilot.utils.agui_chat.threading.Thread") as thread,
        ):
            chunks = asyncio.run(_run())
        return chunks, thread

    def test_yields_skill_view_parses_json_skips_invalid_and_logs(self):
        class FakeGraph:
            async def agui_stream(self, _request):
                yield 'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "hi"}\n\n'
                yield "data: {not-json\n\n"
                yield 'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "!"}\n\n'

        params = {"matched_skill_packages": [{"id": "k8s", "name": "K8s"}]}
        stats = {"content": []}
        chunks, thread = self._collect(params, FakeGraph(), final_stats=stats)
        text = "".join(chunks)
        assert "skill_view" in text
        assert "hi" in text
        assert "!" in text
        assert stats["content"]
        thread.assert_called_once()

    def test_interrupt_stops_stream(self):
        class FakeGraph:
            async def agui_stream(self, _request):
                yield 'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "one"}\n\n'
                yield 'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "two"}\n\n'

        interrupt = AsyncMock(side_effect=[False, True])
        chunks, _ = self._collect({}, FakeGraph(), interrupt=interrupt)
        text = "".join(chunks)
        assert "INTERRUPTED" in text
        assert "two" not in text

    def test_exception_yields_error_event(self):
        class FakeGraph:
            async def agui_stream(self, _request):
                raise RuntimeError("agent exploded")
                yield  # make this an async generator

        chunks, _ = self._collect({}, FakeGraph())
        payloads = _payloads(chunks)
        assert payloads[-1]["type"] == "ERROR"
        assert "agent exploded" in payloads[-1]["error"]

    def test_stream_agui_chat_wraps_generator_in_sse_response(self):
        class FakeGraph:
            async def agui_stream(self, _request):
                yield 'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "ok"}\n\n'

        def fake_sync_to_async(fn, thread_sensitive=True):
            async def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)

            return wrapper

        with (
            patch("apps.opspilot.utils.agui_chat.sync_to_async", side_effect=fake_sync_to_async),
            patch("apps.opspilot.utils.agui_chat._prepare_agui_chat_kwargs", return_value={}),
            patch("apps.opspilot.utils.agui_chat.create_agent_instance", return_value=(FakeGraph(), self._request())),
            patch("apps.opspilot.utils.agui_chat.is_interrupt_requested_async", new=AsyncMock(return_value=False)),
            patch("apps.opspilot.utils.agui_chat.create_sse_response_headers", return_value={"X-Test": "1"}),
            patch("apps.opspilot.utils.agui_chat.threading.Thread"),
        ):
            resp = stream_agui_chat({"show_think": False, "skill_type": "chat"}, "s", {}, "1.1.1.1", "hi")

            async def _read():
                parts = []
                async for part in resp.streaming_content:
                    parts.append(part.decode() if isinstance(part, bytes) else part)
                return "".join(parts)

            text = asyncio.run(_read())
        assert "ok" in text
        assert resp["X-Test"] == "1"
