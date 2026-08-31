"""钉钉 ChatFlow handle_dingtalk_message：非法 JSON、非文本、空文本、验签失败与投递。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.http import JsonResponse

from apps.opspilot.services.dingtalk_chat_flow_utils import DingTalkChatFlowUtils

pytestmark = pytest.mark.unit


def _req(body, headers=None):
    return SimpleNamespace(body=body if isinstance(body, (bytes, str)) else json.dumps(body).encode(), headers=headers or {})


def test_handle_dingtalk_invalid_json_returns_failure():
    utils = DingTalkChatFlowUtils(bot_id=2)
    resp = utils.handle_dingtalk_message(_req(b"{"), None, {"client_secret": "s"})
    assert isinstance(resp, JsonResponse)
    payload = json.loads(resp.content)
    assert payload["success"] is False


def test_handle_dingtalk_ignores_non_text_and_empty():
    utils = DingTalkChatFlowUtils(bot_id=2)
    resp = utils.handle_dingtalk_message(_req({"msgtype": "image"}), None, {})
    assert json.loads(resp.content)["success"] is True
    resp = utils.handle_dingtalk_message(
        _req({"msgtype": "text", "text": {"content": ""}, "senderStaffId": "u"}),
        None,
        {},
    )
    assert json.loads(resp.content)["success"] is True


def test_handle_dingtalk_rejects_bad_signature_and_enqueues_text():
    utils = DingTalkChatFlowUtils(bot_id=4)
    with patch.object(utils, "verify_signature", return_value=False):
        resp = utils.handle_dingtalk_message(
            _req({"msgtype": "text", "text": {"content": "hi"}}, {"timestamp": "t", "sign": "bad"}),
            None,
            {"client_secret": "sec"},
        )
    assert json.loads(resp.content)["success"] is False
    assert json.loads(resp.content)["message"] == "Invalid signature"

    with patch.object(utils, "verify_signature", return_value=True), patch.object(
        utils, "is_message_processed", return_value=False
    ), patch("apps.opspilot.tasks.process_dingtalk_message.delay") as delay:
        resp = utils.handle_dingtalk_message(
            _req(
                {
                    "msgtype": "text",
                    "text": {"content": "hello"},
                    "senderStaffId": "u1",
                    "msgId": "m1",
                    "sessionWebhook": "https://oapi.dingtalk.com/hook",
                },
                {"timestamp": "t", "sign": "ok"},
            ),
            None,
            {"client_secret": "sec"},
        )
    assert json.loads(resp.content)["success"] is True
    delay.assert_called_once()
    assert delay.call_args.kwargs["bot_id"] == 4
    assert delay.call_args.kwargs["text_content"] == "hello"
    assert delay.call_args.kwargs["sender_id"] == "u1"
