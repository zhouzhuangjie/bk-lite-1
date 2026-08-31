"""views.skill_execute / get_skill_execute_result：JSON、频道映射、执行失败与 api_pass 记日志。"""
import json
from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from apps.opspilot import views

pytestmark = pytest.mark.django_db
rf = RequestFactory()


def _json_request(body, token="tok", api_pass=False):
    request = rf.post("/", data=json.dumps(body).encode("utf-8"), content_type="application/json")
    request.META["HTTP_AUTHORIZATION"] = f"TOKEN {token}"
    request.api_pass = api_pass
    return request


def test_skill_execute_rejects_invalid_json():
    request = rf.post("/", data=b"{bad", content_type="application/json")
    resp = views.skill_execute(request)
    assert resp.status_code == 400
    body = json.loads(resp.content)
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert "Invalid JSON" in body["choices"][0]["message"]["content"]


def test_skill_execute_maps_socketio_channel_to_web(monkeypatch):
    captured = {}

    def _result(bot_id, channel, chat_history, kwargs, request, sender_id, skill_id, user_message):
        captured.update(
            bot_id=bot_id,
            channel=channel,
            chat_history=chat_history,
            sender_id=sender_id,
            skill_id=skill_id,
            user_message=user_message,
        )
        return {"content": "ok"}

    monkeypatch.setattr(views, "get_skill_execute_result", _result)
    resp = views.skill_execute(
        _json_request(
            {
                "bot_id": 9,
                "skill_id": 3,
                "user_message": "hi",
                "sender_id": "u1",
                "chat_history": [{"role": "user"}],
                "channel": "socketio",
            }
        )
    )
    assert json.loads(resp.content) == {"result": {"content": "ok"}}
    assert captured == {
        "bot_id": 9,
        "channel": "web",
        "chat_history": [{"role": "user"}],
        "sender_id": "u1",
        "skill_id": 3,
        "user_message": "hi",
    }


def test_get_skill_execute_result_swallows_execution_error_and_logs_when_api_pass(monkeypatch):
    monkeypatch.setattr(
        views,
        "get_loader",
        lambda request=None, default_lang="en": SimpleNamespace(get=lambda key, default=None: default),
    )
    monkeypatch.setattr(views, "extract_api_token", lambda request: "tok")
    skill = SimpleNamespace(id=77)
    bot = SimpleNamespace(id=12, llm_skills=SimpleNamespace(first=lambda: skill))
    monkeypatch.setattr(views.Bot.objects, "filter", lambda **kwargs: SimpleNamespace(first=lambda: bot))
    monkeypatch.setattr(
        views.SkillExecuteService,
        "execute_skill",
        staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skill-down"))),
    )
    logged = {}

    def _log(ip, skill_id, result, kwargs, user_message=""):
        logged.update(ip=ip, skill_id=skill_id, result=result, user_message=user_message)

    monkeypatch.setattr(views, "insert_skill_log", _log)
    monkeypatch.setattr(views, "get_client_ip", lambda request: ("10.0.0.8", True))
    request = _json_request({"bot_id": 12, "skill_id": 3, "user_message": "hi"}, api_pass=True)
    out = views.get_skill_execute_result(12, "web", [], {"bot_id": 12}, request, "s1", 3, "hi")
    assert out == {"content": "Skill execution error"}
    assert logged == {
        "ip": "10.0.0.8",
        "skill_id": 77,
        "result": {"content": "Skill execution error"},
        "user_message": "hi",
    }
