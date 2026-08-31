"""微信公众号：URL 验签、空回复、重复消息与签名失败。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from wechatpy.exceptions import InvalidSignatureException

from apps.opspilot.services.wechat_official_chat_flow_utils import WechatOfficialChatFlowUtils

pytestmark = pytest.mark.unit


def _utils():
    u = WechatOfficialChatFlowUtils.__new__(WechatOfficialChatFlowUtils)
    u.bot_id = 4
    return u


def test_handle_url_verification_echostr_and_signature_errors():
    utils = _utils()
    assert utils.handle_url_verification("s", "t", "n", "", "token", "k", "a").content == b"fail"
    with patch("apps.opspilot.services.wechat_official_chat_flow_utils.check_signature"):
        assert utils.handle_url_verification("s", "t", "n", "echo", "token", "k", "a").content == b"echo"
    with patch(
        "apps.opspilot.services.wechat_official_chat_flow_utils.check_signature",
        side_effect=InvalidSignatureException(),
    ):
        assert utils.handle_url_verification("s", "t", "n", "echo", "token", "k", "a").content == b"fail"
    with patch(
        "apps.opspilot.services.wechat_official_chat_flow_utils.check_signature",
        side_effect=RuntimeError("timeout"),
    ):
        assert utils.handle_url_verification("s", "t", "n", "echo", "token", "k", "a").content == b"fail"


def test_send_reply_skips_empty_and_swallows_send_error():
    utils = _utils()
    with patch.object(utils, "send_message_chunks") as send:
        utils.send_reply("", "oid", {"appid": "a", "secret": "s"})
        send.assert_not_called()
        utils.send_reply("hello\r\nworld", "oid", {"appid": "a", "secret": "s"})
        send.assert_called_once_with("oid", "hello\nworld", "a", "s")
        send.side_effect = RuntimeError("api down")
        utils.send_reply("hi", "oid", {"appid": "a", "secret": "s"})


def test_handle_wechat_message_empty_duplicate_and_signature_error():
    utils = _utils()
    req = SimpleNamespace(GET={"signature": "s", "timestamp": "1", "nonce": "n"}, body=b"<xml></xml>")
    empty = SimpleNamespace(type="text", content="", source="u", id="m1")
    with (
        patch(
            "apps.opspilot.services.wechat_official_chat_flow_utils.xmltodict.parse",
            return_value={"xml": {"Encrypt": "enc"}},
        ),
        patch.object(utils, "decrypt", return_value="<xml/>"),
        patch("apps.opspilot.services.wechat_official_chat_flow_utils.parse_message", return_value=empty),
    ):
        assert utils.handle_wechat_message(req, {"aes_key": "k", "appid": "a"}, None).content == b"success"

    msg = SimpleNamespace(type="text", content="hi", source="u", id="m2")
    with (
        patch(
            "apps.opspilot.services.wechat_official_chat_flow_utils.xmltodict.parse",
            return_value={"xml": {"Encrypt": "enc"}},
        ),
        patch.object(utils, "decrypt", return_value="<xml/>"),
        patch("apps.opspilot.services.wechat_official_chat_flow_utils.parse_message", return_value=msg),
        patch.object(utils, "is_message_processed", return_value=True),
    ):
        assert utils.handle_wechat_message(req, {"aes_key": "k", "appid": "a"}, None).content == b"success"

    with (
        patch(
            "apps.opspilot.services.wechat_official_chat_flow_utils.xmltodict.parse",
            return_value={"xml": {"Encrypt": "enc"}},
        ),
        patch.object(utils, "decrypt", side_effect=InvalidSignatureException()),
    ):
        assert utils.handle_wechat_message(req, {"aes_key": "k", "appid": "a"}, None).content == b"success"

    with (
        patch(
            "apps.opspilot.services.wechat_official_chat_flow_utils.xmltodict.parse",
            side_effect=RuntimeError("bad xml"),
        ),
    ):
        assert utils.handle_wechat_message(req, {"aes_key": "k", "appid": "a"}, None).content == b"success"
