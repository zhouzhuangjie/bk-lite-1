"""EncryptedJsonResponse：加密头命中、加密失败回退与未加密 JSON。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.node_mgmt.utils.crypto_helper import EncryptedJsonResponse, encrypt_response_data

pytestmark = pytest.mark.unit


def test_encrypted_json_response_encrypts_when_header_present():
    request = SimpleNamespace(META={"HTTP_X_ENCRYPTION_KEY": "12345678-1234-1234-1234-123456789abc"})
    resp = EncryptedJsonResponse({"ok": True}, request=request)
    assert resp["Content-Encoding"] == "encrypted"
    assert resp["Content-Type"] == "application/json"
    assert resp.content.decode("ascii") != json.dumps({"ok": True})


def test_encrypted_json_response_falls_back_when_encrypt_fails():
    request = SimpleNamespace(META={"HTTP_X_ENCRYPTION_KEY": "k"})
    with patch("apps.node_mgmt.utils.crypto_helper.encrypt_response_data", side_effect=RuntimeError("boom")):
        resp = EncryptedJsonResponse({"ok": True}, request=request)
    assert json.loads(resp.content) == {"ok": True}
    assert "Content-Encoding" not in resp


def test_encrypted_json_response_plain_json_and_safe_list():
    resp = EncryptedJsonResponse({"a": 1})
    assert json.loads(resp.content) == {"a": 1}
    with pytest.raises(TypeError, match="non-dict objects"):
        EncryptedJsonResponse([1, 2], request=None, safe=True)
    uuid_key = "12345678-1234-1234-1234-123456789abc"
    assert encrypt_response_data("plain-text", uuid_key)
    assert encrypt_response_data(123, uuid_key)
    with patch("apps.node_mgmt.utils.crypto_helper.AESGCM", side_effect=RuntimeError("no-aes")):
        with pytest.raises(Exception, match="Encryption failed"):
            encrypt_response_data({"ok": True}, uuid_key)
