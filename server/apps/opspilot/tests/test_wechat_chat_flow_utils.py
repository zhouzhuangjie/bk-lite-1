"""企业微信 ChatFlow：解析消息、节点配置校验、URL 验证与分片发送。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.http import HttpResponse

from apps.opspilot.utils.wechat_chat_flow_utils import WechatChatFlowUtils

pytestmark = pytest.mark.unit


def test_parse_message_empty_and_text_event():
    assert WechatChatFlowUtils.parse_message("") is None
    xml = """<xml><MsgType>text</MsgType><Content>hi</Content><FromUserName>u1</FromUserName></xml>"""
    msg = WechatChatFlowUtils.parse_message(xml)
    assert msg.content == "hi"
    assert msg.source == "u1"
    event_xml = """<xml><MsgType>event</MsgType><Event>subscribe</Event><FromUserName>u1</FromUserName></xml>"""
    event = WechatChatFlowUtils.parse_message(event_xml)
    assert event.event == "subscribe"
    assert event.source == "u1"


def test_get_wechat_node_config_missing_node_and_params():
    utils = WechatChatFlowUtils(bot_id=7)
    flow = SimpleNamespace(flow_json={"nodes": [{"id": "n1", "type": "agent"}]})
    cfg, resp = utils.get_wechat_node_config(flow)
    assert cfg is None
    assert isinstance(resp, HttpResponse)

    flow2 = SimpleNamespace(
        flow_json={
            "nodes": [
                {
                    "id": "wx",
                    "type": "enterprise_wechat",
                    "data": {"config": {"token": "t"}},
                }
            ]
        }
    )
    cfg2, resp2 = utils.get_wechat_node_config(flow2)
    assert cfg2 is None
    assert isinstance(resp2, HttpResponse)

    flow3 = SimpleNamespace(
        flow_json={
            "nodes": [
                {
                    "id": "wx",
                    "type": "enterprise_wechat",
                    "data": {
                        "config": {
                            "token": "t",
                            "aes_key": "a",
                            "corp_id": "c",
                            "agent_id": "1",
                            "secret": "s",
                        }
                    },
                }
            ]
        }
    )
    cfg3, resp3 = utils.get_wechat_node_config(flow3)
    assert resp3 is None
    assert cfg3["node_id"] == "wx"
    assert cfg3["corp_id"] == "c"


def test_handle_url_verification_success_and_fail():
    utils = WechatChatFlowUtils(bot_id=8)
    assert utils.handle_url_verification(MagicMock(), "s", "t", "n", "").content == b"fail"
    crypto = MagicMock()
    crypto.check_signature.return_value = "echo-ok"
    ok = utils.handle_url_verification(crypto, "s", "t", "n", "echo")
    assert ok.content == b"echo-ok"
    crypto.check_signature.side_effect = ValueError("bad")
    fail = utils.handle_url_verification(crypto, "s", "t", "n", "echo")
    assert fail.content == b"fail"


def test_send_message_chunks_skips_empty_and_splits_long_text():
    utils = WechatChatFlowUtils(bot_id=9)
    utils.send_message_chunks("u", "", "agent", "corp", "secret")
    client = MagicMock()
    with patch("apps.opspilot.utils.wechat_chat_flow_utils.WeChatClient", return_value=client):
        utils.send_message_chunks("u", "short", "agent", "corp", "secret")
    client.message.send_markdown.assert_called_once_with("agent", "u", "short")

    long_text = "x" * 501
    client2 = MagicMock()
    with patch("apps.opspilot.utils.wechat_chat_flow_utils.WeChatClient", return_value=client2), patch(
        "apps.opspilot.utils.wechat_chat_flow_utils.time.sleep"
    ):
        utils.send_message_chunks("u", long_text, "agent", "corp", "secret")
    assert client2.message.send_markdown.call_count == 2
