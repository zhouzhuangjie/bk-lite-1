"""企业微信 / 公众号 ChatFlow：空消息短路与分片发送。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.services.wechat_official_chat_flow_utils import WechatOfficialChatFlowUtils
from apps.opspilot.utils.wechat_chat_flow_utils import WechatChatFlowUtils

pytestmark = pytest.mark.unit


def test_wechat_official_send_chunks_skips_empty_and_splits():
    utils = WechatOfficialChatFlowUtils.__new__(WechatOfficialChatFlowUtils)
    utils.bot_id = 1
    client = MagicMock()
    with patch("apps.opspilot.services.wechat_official_chat_flow_utils.WeChatClient", return_value=client):
        utils.send_message_chunks("oid", "", "app", "sec")
        client.message.send_text.assert_not_called()
        utils.send_message_chunks("oid", "short", "app", "sec")
        client.message.send_text.assert_called_once_with("oid", "short")
        client.message.send_text.reset_mock()
        utils.send_message_chunks("oid", "x" * 1900, "app", "sec")
        assert client.message.send_text.call_count == 2


def test_enterprise_wechat_send_chunks_splits_over_500():
    utils = WechatChatFlowUtils.__new__(WechatChatFlowUtils)
    utils.bot_id = 1
    client = MagicMock()
    with (
        patch("apps.opspilot.utils.wechat_chat_flow_utils.WeChatClient", return_value=client),
        patch("apps.opspilot.utils.wechat_chat_flow_utils.time.sleep"),
    ):
        utils.send_message_chunks("u1", "", 9, "corp", "sec")
        client.message.send_markdown.assert_not_called()
        utils.send_message_chunks("u1", "hi", 9, "corp", "sec")
        client.message.send_markdown.assert_called_once_with(9, "u1", "hi")
        client.message.send_markdown.reset_mock()
        utils.send_message_chunks("u1", "y" * 1100, 9, "corp", "sec")
        assert client.message.send_markdown.call_count == 3
