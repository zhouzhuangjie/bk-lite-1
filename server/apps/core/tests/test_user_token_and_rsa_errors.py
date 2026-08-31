"""Core 实体与 RSA 生成/加解密异常契约。"""
from unittest.mock import patch

import pytest

from apps.core.entities.user_token_entity import UserTokenEntity
from apps.core.utils.crypto.rsa_crypto import RSACryptor


def test_user_token_entity_defaults():
    ok = UserTokenEntity(success=True, token="tok")
    assert ok.success is True
    assert ok.token == "tok"
    assert ok.error_message is None
    failed = UserTokenEntity(success=False, error_message="bad creds")
    assert failed.success is False
    assert failed.error_message == "bad creds"
    assert failed.token is None


def test_rsa_rejects_too_small_key_and_empty_inputs():
    with pytest.raises(ValueError, match="密钥长度不能小于 1024 位"):
        RSACryptor(bits=512)
    r = RSACryptor(bits=1024)
    with pytest.raises(ValueError, match="待加密文本不能为空"):
        r.encrypt_rsa("", r.public_key)
    with pytest.raises(ValueError, match="公钥不能为空"):
        r.encrypt_rsa("plain", "")
    with pytest.raises(ValueError, match="待解密文本不能为空"):
        r.decrypt_rsa("", r.private_key)
    with pytest.raises(ValueError, match="私钥不能为空"):
        r.decrypt_rsa("cipher", "")


def test_rsa_generate_and_cipher_generic_errors():
    with patch("apps.core.utils.crypto.rsa_crypto.RSA.generate", side_effect=RuntimeError("rng")):
        with pytest.raises(RuntimeError, match="rng"):
            RSACryptor(bits=1024)

    r = RSACryptor(bits=1024)
    with patch("apps.core.utils.crypto.rsa_crypto.PKCS1_OAEP.new") as new:
        new.return_value.encrypt.side_effect = OSError("hw")
        with pytest.raises(OSError, match="hw"):
            r.encrypt_rsa("plain", r.public_key)

    cipher = r.encrypt_rsa("plain", r.public_key)
    with patch("apps.core.utils.crypto.rsa_crypto.PKCS1_OAEP.new") as new:
        new.return_value.decrypt.side_effect = OSError("hw2")
        with pytest.raises(OSError, match="hw2"):
            r.decrypt_rsa(cipher, r.private_key)
