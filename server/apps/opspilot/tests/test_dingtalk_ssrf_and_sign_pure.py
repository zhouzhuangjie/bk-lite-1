"""钉钉 ChatFlow：SSRF 域名校验与签名验证。"""
from base64 import b64encode
import hashlib
import hmac

import pytest

from apps.opspilot.services.dingtalk_chat_flow_utils import DingTalkChatFlowUtils, is_valid_dingtalk_url

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "url,ok",
    [
        ("", False),
        ("https://oapi.dingtalk.com/robot/send", True),
        ("https://api.dingtalk.com/v1", True),
        ("https://open.dingtalk.com/path", True),
        ("http://evil.com", False),
        ("https://oapi.dingtalk.com.evil.com", False),
        (r"https://oapi.dingtalk.com\evil", False),
        ("https://user@oapi.dingtalk.com", False),
        ("ftp://oapi.dingtalk.com", False),
        ("https://oapi%2edingtalk.com", False),
    ],
)
def test_is_valid_dingtalk_url(url, ok):
    assert is_valid_dingtalk_url(url) is ok


def test_verify_signature_accepts_matching_hmac():
    utils = DingTalkChatFlowUtils.__new__(DingTalkChatFlowUtils)
    utils.bot_id = 1
    ts, secret = "1710000000000", "app-secret"
    expected = b64encode(hmac.new(secret.encode(), f"{ts}\n{secret}".encode(), hashlib.sha256).digest()).decode()
    assert utils.verify_signature(ts, expected, secret) is True
    assert utils.verify_signature(ts, "deadbeef", secret) is False
    assert utils.verify_signature(None, expected, secret) is False
