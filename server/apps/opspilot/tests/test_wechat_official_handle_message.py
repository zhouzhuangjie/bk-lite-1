"""微信公众号 ChatFlow：节点配置、缺签名早退、非文本忽略、文本投递 Celery。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.http import HttpResponse

from apps.opspilot.services.wechat_official_chat_flow_utils import WechatOfficialChatFlowUtils

pytestmark = pytest.mark.unit


def test_official_node_config_missing_node_and_params():
    utils = WechatOfficialChatFlowUtils(bot_id=3)
    cfg, resp = utils.get_wechat_official_node_config(SimpleNamespace(flow_json={"nodes": []}))
    assert cfg is None
    assert isinstance(resp, HttpResponse)
    flow = SimpleNamespace(
        flow_json={
            "nodes": [
                {"id": "wx", "type": "wechat_official", "data": {"config": {"token": "t"}}}
            ]
        }
    )
    cfg, resp = utils.get_wechat_official_node_config(flow)
    assert cfg is None
    assert isinstance(resp, HttpResponse)

    ok_flow = SimpleNamespace(
        flow_json={
            "nodes": [
                {
                    "id": "wx",
                    "type": "wechat_official",
                    "data": {"config": {"token": "t", "appid": "a", "secret": "s", "aes_key": "k"}},
                }
            ]
        }
    )
    cfg, resp = utils.get_wechat_official_node_config(ok_flow)
    assert resp is None
    assert cfg["node_id"] == "wx"
    assert cfg["appid"] == "a"


def test_handle_wechat_message_missing_signature_and_non_text():
    utils = WechatOfficialChatFlowUtils(bot_id=3)
    req = SimpleNamespace(GET={}, body=b"")
    resp = utils.handle_wechat_message(req, {}, None)
    assert resp.content == b"success"

    req2 = SimpleNamespace(
        GET={"signature": "sig", "timestamp": "1", "nonce": "n"},
        body=b"<xml></xml>",
    )
    msg = SimpleNamespace(type="image", content="", source="u1", id="m1")
    with patch(
        "apps.opspilot.services.wechat_official_chat_flow_utils.xmltodict.parse",
        return_value={"xml": {"Encrypt": "enc"}},
    ), patch.object(utils, "decrypt", return_value="<xml/>"), patch(
        "apps.opspilot.services.wechat_official_chat_flow_utils.parse_message",
        return_value=msg,
    ):
        resp = utils.handle_wechat_message(req2, {"aes_key": "k", "appid": "a"}, None)
    assert resp.content == b"success"


def test_handle_wechat_message_text_enqueues_celery():
    utils = WechatOfficialChatFlowUtils(bot_id=8)
    req = SimpleNamespace(
        GET={"msg_signature": "sig", "timestamp": "1", "nonce": "n"},
        body=b"<xml></xml>",
    )
    msg = SimpleNamespace(type="text", content="hello", source="openid-1", id="mid-1")
    with patch(
        "apps.opspilot.services.wechat_official_chat_flow_utils.xmltodict.parse",
        return_value={"xml": {"Encrypt": "enc"}},
    ), patch.object(utils, "decrypt", return_value="<xml/>"), patch(
        "apps.opspilot.services.wechat_official_chat_flow_utils.parse_message",
        return_value=msg,
    ), patch.object(utils, "is_message_processed", return_value=False), patch(
        "apps.opspilot.services.wechat_official_chat_flow_utils.process_wechat_official_message.delay"
    ) as delay:
        resp = utils.handle_wechat_message(
            req, {"aes_key": "k", "appid": "a", "secret": "s"}, None
        )
    assert resp.content == b"success"
    delay.assert_called_once_with(8, "mid-1", "hello", "openid-1", {"aes_key": "k", "appid": "a", "secret": "s"})


def test_send_message_chunks_skips_empty_and_splits_long(monkeypatch):
    utils = WechatOfficialChatFlowUtils(bot_id=1)
    client = MagicMock()
    monkeypatch.setattr(
        "apps.opspilot.services.wechat_official_chat_flow_utils.WeChatClient",
        lambda *a, **k: client,
    )
    monkeypatch.setattr("apps.opspilot.services.wechat_official_chat_flow_utils.time.sleep", lambda *a, **k: None)
    utils.send_message_chunks("o1", "", "app", "sec")
    client.message.send_text.assert_not_called()
    utils.send_message_chunks("o1", "short", "app", "sec")
    client.message.send_text.assert_called_once_with("o1", "short")
    client.message.send_text.reset_mock()
    utils.send_message_chunks("o1", "x" * 1801, "app", "sec")
    assert client.message.send_text.call_count == 2
    assert len(client.message.send_text.call_args_list[0].args[1]) == 1800
