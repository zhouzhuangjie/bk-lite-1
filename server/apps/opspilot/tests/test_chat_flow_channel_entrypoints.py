"""ChatFlow 渠道入口：缺 bot、URL 验证、消息处理与钉钉健康检查。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from apps.opspilot import views

pytestmark = pytest.mark.django_db
rf = RequestFactory()


def test_execute_chat_flow_requires_ids_and_rejects_invalid_token(monkeypatch):
    import asyncio

    monkeypatch.setattr(
        views,
        "get_loader",
        lambda request=None, default_lang="en": SimpleNamespace(get=lambda key, default=None: default),
    )
    empty = asyncio.run(views.execute_chat_flow(rf.post("/", data=b"{}", content_type="application/json"), 0, ""))
    body = json.loads(empty.content)
    assert body["result"] is False
    assert "Bot ID and Node ID are required" in body["message"]

    monkeypatch.setattr(views, "extract_api_token", lambda request: "")
    monkeypatch.setattr(views, "get_current_team", lambda request: 1)
    monkeypatch.setattr(
        views,
        "validate_openai_token",
        lambda token, team=None, is_mobile=False: (False, {"result": False, "message": "invalid token"}),
    )
    denied = asyncio.run(
        views.execute_chat_flow(rf.post("/", data=b'{"message":"hi"}', content_type="application/json"), 12, "n1")
    )
    body = json.loads(denied.content)
    assert body == {"result": False, "message": "invalid token"}


def test_wechat_official_missing_bot_and_get_post_paths(monkeypatch):
    missing = views.execute_chat_flow_wechat_official(rf.get("/"), bot_id=None)
    assert missing.content == b"success"

    utils = MagicMock()
    utils.validate_bot_and_workflow.return_value = (SimpleNamespace(id=1), None)
    utils.get_wechat_official_node_config.return_value = ({"token": "t", "aes_key": "k", "appid": "a"}, None)
    utils.handle_url_verification.return_value = HttpResponse("echo")
    utils.handle_wechat_message.return_value = HttpResponse("msg-ok")
    monkeypatch.setattr(views, "WechatOfficialChatFlowUtils", lambda bot_id: utils)

    get_resp = views.execute_chat_flow_wechat_official(rf.get("/?echostr=echo&signature=s&timestamp=1&nonce=n"), bot_id=8)
    assert get_resp.content == b"echo"
    utils.handle_url_verification.assert_called_once()

    post_resp = views.execute_chat_flow_wechat_official(rf.post("/"), bot_id=8)
    assert post_resp.content == b"msg-ok"
    utils.handle_wechat_message.assert_called_once()


def test_wechat_work_crypto_failure_and_get_post(monkeypatch):
    missing = views.execute_chat_flow_wechat(rf.get("/"), bot_id=None)
    assert missing.content == b"success"

    utils = MagicMock()
    utils.validate_bot_and_workflow.return_value = (SimpleNamespace(id=1), None)
    utils.get_wechat_node_config.return_value = ({"token": "t", "aes_key": "k", "corp_id": "c"}, None)
    utils.handle_url_verification.return_value = HttpResponse("echo-work")
    utils.handle_wechat_message.return_value = HttpResponse("work-ok")
    monkeypatch.setattr(views, "WechatChatFlowUtils", lambda bot_id: utils)
    monkeypatch.setattr(views, "WeChatCrypto", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad-crypto")))
    crypto_fail = views.execute_chat_flow_wechat(rf.get("/"), bot_id=9)
    assert crypto_fail.content == b"success"

    monkeypatch.setattr(views, "WeChatCrypto", lambda *a, **k: "crypto")
    get_resp = views.execute_chat_flow_wechat(rf.get("/?echostr=echo"), bot_id=9)
    assert get_resp.content == b"echo-work"
    post_resp = views.execute_chat_flow_wechat(rf.post("/"), bot_id=9)
    assert post_resp.content == b"work-ok"


def test_dingtalk_get_health_and_missing_bot(monkeypatch):
    monkeypatch.setattr(
        views,
        "get_loader",
        lambda request=None, default_lang="en": SimpleNamespace(get=lambda key, default=None: default),
    )
    health = views.execute_chat_flow_dingtalk(rf.get("/"), bot_id=44)
    assert json.loads(health.content) == {"status": "ok", "bot_id": 44}

    missing = views.execute_chat_flow_dingtalk(rf.post("/", data=b"{}", content_type="application/json"), bot_id=None)
    body = json.loads(missing.content)
    assert body["success"] is False
    assert body["message"] == "Missing bot_id"
