"""企业微信 ChatFlow：节点配置、缺签名、非文本、文本投递 Celery。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.http import HttpResponse

from apps.opspilot.utils.wechat_chat_flow_utils import WechatChatFlowUtils

pytestmark = pytest.mark.unit


def test_enterprise_node_config_missing_and_complete():
    utils = WechatChatFlowUtils(bot_id=4)
    cfg, resp = utils.get_wechat_node_config(SimpleNamespace(flow_json={"nodes": []}))
    assert cfg is None
    assert isinstance(resp, HttpResponse)

    incomplete = SimpleNamespace(
        flow_json={"nodes": [{"id": "wx", "type": "enterprise_wechat", "data": {"config": {"token": "t"}}}]}
    )
    cfg, resp = utils.get_wechat_node_config(incomplete)
    assert cfg is None
    assert isinstance(resp, HttpResponse)

    complete = SimpleNamespace(
        flow_json={
            "nodes": [
                {
                    "id": "wx",
                    "type": "enterprise_wechat",
                    "data": {
                        "config": {
                            "token": "t",
                            "aes_key": "k",
                            "corp_id": "c",
                            "agent_id": "1",
                            "secret": "s",
                        }
                    },
                }
            ]
        }
    )
    cfg, resp = utils.get_wechat_node_config(complete)
    assert resp is None
    assert cfg["node_id"] == "wx"
    assert cfg["corp_id"] == "c"


def test_handle_wechat_message_missing_signature_returns_success():
    utils = WechatChatFlowUtils(bot_id=4)
    req = SimpleNamespace(GET={}, body=b"")
    resp = utils.handle_wechat_message(req, MagicMock(), None, {})
    assert resp.content == b"success"


def test_handle_wechat_message_non_text_and_empty_text():
    utils = WechatChatFlowUtils(bot_id=4)
    crypto = MagicMock()
    crypto.decrypt_message.return_value = "<xml/>"
    req = SimpleNamespace(
        GET={"msg_signature": "sig", "timestamp": "1", "nonce": "n"},
        body=b"<xml></xml>",
    )
    with patch.object(utils, "parse_message", return_value=SimpleNamespace(type="image", content="", source="u", id="m")):
        resp = utils.handle_wechat_message(req, crypto, None, {})
    assert resp.content == b"success"

    with patch.object(
        utils, "parse_message", return_value=SimpleNamespace(type="text", content="", source="u", id="m")
    ):
        resp = utils.handle_wechat_message(req, crypto, None, {})
    assert resp.content == b"success"


def test_handle_wechat_message_text_enqueues_celery():
    utils = WechatChatFlowUtils(bot_id=11)
    crypto = MagicMock()
    crypto.decrypt_message.return_value = "<xml/>"
    req = SimpleNamespace(
        GET={"signature": "sig", "timestamp": "1", "nonce": "n"},
        body=b"<xml></xml>",
    )
    msg = SimpleNamespace(type="text", content="hello", source="user-1", id="mid-9")
    with patch.object(utils, "parse_message", return_value=msg), patch.object(
        utils, "is_message_processed", return_value=False
    ), patch("apps.opspilot.tasks.process_wechat_message.delay") as delay:
        resp = utils.handle_wechat_message(req, crypto, None, {"agent_id": "1"})
    assert resp.content == b"success"
    delay.assert_called_once()
    kwargs = delay.call_args.kwargs
    assert kwargs["bot_id"] == 11
    assert kwargs["message"] == "hello"
    assert kwargs["sender_id"] == "user-1"
    assert kwargs["msg_id"] == "mid-9"
