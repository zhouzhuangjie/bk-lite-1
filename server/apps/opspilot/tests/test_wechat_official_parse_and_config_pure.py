"""微信公众号 ChatFlow：XML 解析与节点配置校验。"""
from types import SimpleNamespace

import pytest
from django.http import HttpResponse

from apps.opspilot.services.wechat_official_chat_flow_utils import WechatOfficialChatFlowUtils

pytestmark = pytest.mark.unit


def _utils():
    u = WechatOfficialChatFlowUtils.__new__(WechatOfficialChatFlowUtils)
    u.bot_id = 1
    return u


def test_parse_message_empty_text_and_event():
    assert WechatOfficialChatFlowUtils.parse_message("") is None
    text_xml = (
        "<xml><ToUserName>gh</ToUserName><FromUserName>u1</FromUserName>"
        "<CreateTime>1</CreateTime><MsgType>text</MsgType><Content>hello</Content><MsgId>1</MsgId></xml>"
    )
    msg = WechatOfficialChatFlowUtils.parse_message(text_xml)
    assert msg.content == "hello"
    assert msg.source == "u1"
    assert msg.target == "gh"
    event_xml = (
        "<xml><ToUserName>gh</ToUserName><FromUserName>u1</FromUserName>"
        "<CreateTime>1</CreateTime><MsgType>event</MsgType><Event>subscribe</Event></xml>"
    )
    event = WechatOfficialChatFlowUtils.parse_message(event_xml)
    assert event.event == "subscribe"
    assert event.source == "u1"


def test_get_wechat_official_node_config_missing_and_required():
    utils = _utils()
    cfg, err = utils.get_wechat_official_node_config(SimpleNamespace(flow_json={"nodes": []}))
    assert cfg is None
    assert isinstance(err, HttpResponse)

    incomplete = SimpleNamespace(
        flow_json={"nodes": [{"type": "wechat_official", "id": "n1", "data": {"config": {"token": "t"}}}]}
    )
    cfg, err = utils.get_wechat_official_node_config(incomplete)
    assert cfg is None
    assert isinstance(err, HttpResponse)

    complete = SimpleNamespace(
        flow_json={
            "nodes": [
                {
                    "type": "wechat_official",
                    "id": "n1",
                    "data": {"config": {"token": "t", "appid": "a", "secret": "s", "aes_key": "k"}},
                }
            ]
        }
    )
    cfg, err = utils.get_wechat_official_node_config(complete)
    assert err is None
    assert cfg["node_id"] == "n1"
    assert cfg["appid"] == "a"
