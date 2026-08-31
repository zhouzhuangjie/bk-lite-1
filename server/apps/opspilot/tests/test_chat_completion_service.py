"""ChatCompletionService：解析失败、鉴权失败、技能错误与异常信封。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.opspilot.services.chat_completion_service import ChatCompletionService

pytestmark = pytest.mark.unit


def _svc(**overrides):
    defaults = dict(
        parse_json_body=lambda req: ({"stream": False}, None),
        extract_api_token=lambda req: "tok",
        get_client_ip=lambda req: ("1.1.1.1", None),
        generate_stream_error=lambda msg: f"stream:{msg}",
        insert_skill_log=MagicMock(),
        invoke_chat=lambda *a, **k: "invoked",
        stream_chat=lambda *a, **k: "streamed",
    )
    defaults.update(overrides)
    return ChatCompletionService(**defaults)


def _body(resp):
    return json.loads(resp.content)


def test_parse_error_returns_400_envelope():
    svc = _svc(parse_json_body=lambda req: (None, "bad json"))
    resp = svc.run(object(), validate=lambda *a: (True, None), resolve_skill=lambda *a: (None, None, None), get_user_id=lambda u: "u")
    assert resp.status_code == 400
    assert _body(resp)["choices"][0]["message"]["content"] == "bad json"


def test_invalid_token_json_and_stream():
    err = {"choices": [{"message": {"role": "assistant", "content": "unauthorized"}}]}
    svc = _svc()
    resp = svc.run(object(), validate=lambda *a: (False, err), resolve_skill=lambda *a: (None, None, None), get_user_id=lambda u: "u")
    assert _body(resp) == err

    stream_svc = _svc(parse_json_body=lambda req: ({"stream": True}, None))
    assert (
        stream_svc.run(object(), validate=lambda *a: (False, err), resolve_skill=lambda *a: (None, None, None), get_user_id=lambda u: "u")
        == "stream:unauthorized"
    )


def test_skill_error_logs_and_returns_envelope():
    skill = SimpleNamespace(id=9, name="s1", enable_km_route=False, km_llm_model=None, enable_suggest=False, enable_query_rewrite=False)
    params = {"user_message": "hi"}
    err = {"choices": [{"message": {"role": "assistant", "content": "no skill"}}]}
    insert = MagicMock()
    svc = _svc(insert_skill_log=insert)
    resp = svc.run(
        object(),
        validate=lambda *a: (True, SimpleNamespace(username="alice")),
        resolve_skill=lambda body, user: (skill, params, err),
        get_user_id=lambda u: u.username,
    )
    insert.assert_called_once_with("1.1.1.1", 9, err, {"stream": False}, False, "hi")
    assert _body(resp) == err

    stream_svc = _svc(parse_json_body=lambda req: ({"stream": True}, None), insert_skill_log=insert)
    assert (
        stream_svc.run(
            object(),
            validate=lambda *a: (True, SimpleNamespace(username="alice")),
            resolve_skill=lambda body, user: (skill, params, err),
            get_user_id=lambda u: u.username,
        )
        == "stream:no skill"
    )


def test_resolve_exception_json_and_stream():
    svc = _svc()
    resp = svc.run(
        object(),
        validate=lambda *a: (True, SimpleNamespace(username="alice")),
        resolve_skill=lambda *a: (_ for _ in ()).throw(RuntimeError("boom")),
        get_user_id=lambda u: "u",
    )
    assert _body(resp)["choices"][0]["message"]["content"] == "boom"

    stream_svc = _svc(parse_json_body=lambda req: ({"stream": True}, None))
    assert (
        stream_svc.run(
            object(),
            validate=lambda *a: (True, SimpleNamespace(username="alice")),
            resolve_skill=lambda *a: (_ for _ in ()).throw(RuntimeError("boom")),
            get_user_id=lambda u: "u",
        )
        == "stream:boom"
    )
