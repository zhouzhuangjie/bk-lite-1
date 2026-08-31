"""LLMViewSet.execute / execute_agui：技能不存在与无权限时走错误流，不调用 LLM。"""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.base.tests.factories import UserFactory
from apps.opspilot.models import LLMSkill
from apps.opspilot.viewsets.llm_view import LLMViewSet

pytestmark = pytest.mark.django_db


def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _request(user, data, forwarded=None):
    meta = {"REMOTE_ADDR": "10.0.0.1"}
    if forwarded:
        meta["HTTP_X_FORWARDED_FOR"] = forwarded
    return SimpleNamespace(data=data, user=user, META=meta, COOKIES={"current_team": "1"})


def _stream_text(resp):
    async def _collect():
        chunks = []
        async for part in resp.streaming_content:
            chunks.append(part.decode() if isinstance(part, bytes) else part)
        return "".join(chunks)

    return asyncio.run(_collect())


def test_execute_missing_skill_streams_not_found():
    user = UserFactory(username="llm-exec", domain="domain.com", roles=[], is_superuser=True)
    view = LLMViewSet()
    view.loader = None
    resp = _unwrap(LLMViewSet.execute)(view, _request(user, {"skill_id": 999999, "user_message": "hi"}))
    text = _stream_text(resp)
    assert "Skill not found" in text
    assert "[DONE]" in text


def test_execute_denies_non_owner_without_permission():
    user = UserFactory(username="llm-guest", domain="domain.com", roles=[], is_superuser=False)
    skill = LLMSkill.objects.create(name="locked", team=[1])
    view = LLMViewSet()
    view.loader = None
    with patch.object(LLMViewSet, "get_has_permission", return_value=False):
        resp = _unwrap(LLMViewSet.execute)(view, _request(user, {"skill_id": skill.id, "user_message": "hi"}))
    text = _stream_text(resp)
    assert "permission" in text.lower()


def test_execute_agui_missing_skill_and_success_calls_stream():
    user = UserFactory(username="llm-agui", domain="domain.com", roles=[], is_superuser=True)
    view = LLMViewSet()
    view.loader = None
    missing = _unwrap(LLMViewSet.execute_agui)(view, _request(user, {"skill_id": 999999, "user_message": "hi"}))
    text = _stream_text(missing)
    assert "Skill not found" in text

    skill = LLMSkill.objects.create(name="ok-skill", team=[1], tools=[], skill_params=[])
    with patch("apps.opspilot.viewsets.llm_view.stream_agui_chat", return_value="agui-ok") as stream:
        ok = _unwrap(LLMViewSet.execute_agui)(
            view, _request(user, {"skill_id": skill.id, "user_message": "hello"}, forwarded="1.1.1.1, 2.2.2.2")
        )
    assert ok == "agui-ok"
    args = stream.call_args.args
    assert args[1] == "ok-skill"
    assert args[3] == "1.1.1.1"
    assert args[4] == "hello"


def test_execute_success_merges_skill_defaults_and_streams():
    user = UserFactory(username="llm-ok", domain="domain.com", roles=[], is_superuser=True)
    skill = LLMSkill.objects.create(
        name="exec-skill",
        team=[1],
        tools=[{"name": "ping"}],
        skill_params=[],
        show_think=True,
        enable_km_route=True,
        enable_suggest=True,
        enable_query_rewrite=False,
    )
    view = LLMViewSet()
    view.loader = None
    with (
        patch("apps.opspilot.viewsets.llm_view.stream_chat", return_value="chat-ok") as stream,
        patch.object(LLMViewSet, "_apply_skill_packages_to_params"),
    ):
        ok = _unwrap(LLMViewSet.execute)(view, _request(user, {"skill_id": skill.id, "user_message": "ping"}))
    assert ok == "chat-ok"
    params = stream.call_args.args[0]
    assert params["group"] == 1
    assert params["show_think"] is True
    assert params["tools"]
    assert stream.call_args.args[4] == "ping"
    assert stream.call_args.args[3] == "10.0.0.1"


def test_execute_exception_streams_error():
    user = UserFactory(username=f"llm-exc-{uuid.uuid4().hex[:8]}", domain="domain.com", roles=[], is_superuser=True)
    skill = LLMSkill.objects.create(name="boom-skill", team=[1], tools=[], skill_params=[])
    view = LLMViewSet()
    view.loader = None
    with (
        patch("apps.opspilot.viewsets.llm_view.stream_chat", side_effect=RuntimeError("llm down")),
        patch.object(LLMViewSet, "_apply_skill_packages_to_params"),
    ):
        resp = _unwrap(LLMViewSet.execute)(view, _request(user, {"skill_id": skill.id, "user_message": "hi"}))
    text = _stream_text(resp)
    assert "llm down" in text
    assert "[DONE]" in text


def test_execute_agui_denies_non_owner_without_permission():
    user = UserFactory(username=f"llm-agui-guest-{uuid.uuid4().hex[:8]}", domain="domain.com", roles=[], is_superuser=False)
    skill = LLMSkill.objects.create(name="locked-agui", team=[1])
    view = LLMViewSet()
    view.loader = None
    with patch.object(LLMViewSet, "get_has_permission", return_value=False):
        resp = _unwrap(LLMViewSet.execute_agui)(view, _request(user, {"skill_id": skill.id, "user_message": "hi"}))
    text = _stream_text(resp)
    assert "permission" in text.lower()


def test_execute_agui_uses_remote_addr_and_exception_stream():
    user = UserFactory(username=f"llm-agui-ip-{uuid.uuid4().hex[:8]}", domain="domain.com", roles=[], is_superuser=True)
    skill = LLMSkill.objects.create(name="agui-ip", team=[1], tools=[], skill_params=[])
    view = LLMViewSet()
    view.loader = None
    with (
        patch("apps.opspilot.viewsets.llm_view.stream_agui_chat", return_value="agui-remote") as stream,
        patch.object(LLMViewSet, "_apply_skill_packages_to_params"),
    ):
        ok = _unwrap(LLMViewSet.execute_agui)(view, _request(user, {"skill_id": skill.id, "user_message": "hello"}))
    assert ok == "agui-remote"
    assert stream.call_args.args[3] == "10.0.0.1"

    with (
        patch("apps.opspilot.viewsets.llm_view.stream_agui_chat", side_effect=RuntimeError("agui down")),
        patch.object(LLMViewSet, "_apply_skill_packages_to_params"),
    ):
        err = _unwrap(LLMViewSet.execute_agui)(view, _request(user, {"skill_id": skill.id, "user_message": "hello"}))
    text = _stream_text(err)
    assert "agui down" in text
    assert "[DONE]" in text
