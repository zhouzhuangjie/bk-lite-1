"""system_mgmt.nats_api：token / 登录锁定 / 错误与操作日志。

对照鉴权契约：JWT 校验失败拒绝；账号锁定拒绝登录；操作类型非法拒绝写审计。
"""
from datetime import timedelta
from unittest.mock import patch

import jwt
import pytest
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from apps.system_mgmt import nats_api
from apps.system_mgmt.models import ErrorLog, OperationLog, SystemSettings, User

pytestmark = pytest.mark.django_db


def _user(**kwargs):
    defaults = dict(
        username="nats-user",
        display_name="nats-user",
        email="nats-user@example.com",
        password=make_password("secret-pass"),
        domain="domain.com",
        group_list=[1],
    )
    defaults.update(kwargs)
    return User.objects.create(**defaults)


def test_verify_token_missing_and_invalid():
    assert nats_api.verify_token("") == {"result": False, "message": "Token is missing"}
    bad = nats_api.verify_token("not-a-jwt")
    assert bad["result"] is False
    assert "message" in bad


def test_verify_token_legacy_expired_and_user_missing(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    token = jwt.encode({"user_id": 999999, "login_time": 1}, "test-secret", algorithm="HS256")
    result = nats_api.verify_token(token)
    assert result["result"] is False
    assert "Token is invalid" in result["message"] or "not found" in result["message"].lower() or "User" in result["message"]


def test_get_pilot_permission_by_token_rejects_bad_token():
    assert nats_api.get_pilot_permission_by_token("bad", bot_id=1, group_list=[1]) == {"result": False}


def test_login_rejects_unknown_user_and_locked_account():
    unknown = nats_api.login("nobody", "x")
    assert unknown["result"] is False

    user = _user(username="locked-user", account_locked_until=timezone.now() + timedelta(minutes=10))
    locked = nats_api.login("locked-user", "secret-pass")
    assert locked["result"] is False
    assert "lock" in locked["message"].lower() or "锁定" in locked["message"]
    user.delete()


def test_login_wrong_password_increments_error_count(monkeypatch):
    user = _user(username="retry-user", password_error_count=0)
    monkeypatch.setattr(
        nats_api,
        "_get_pwd_policy_settings",
        lambda: {"pwd_set_max_retry_count": 3, "pwd_set_lock_duration": 60},
    )
    result = nats_api.login("retry-user", "wrong")
    assert result["result"] is False
    user.refresh_from_db()
    assert user.password_error_count == 1
    assert user.account_locked_until is None


def test_save_error_log_persists_and_handles_failure():
    ok = nats_api.save_error_log("alice", "cmdb", "host", "boom", domain="domain.com")
    assert ok["result"] is True
    assert ErrorLog.objects.filter(username="alice", app="cmdb", module="host").exists()

    with patch.object(ErrorLog.objects, "create", side_effect=RuntimeError("db down")):
        failed = nats_api.save_error_log("alice", "cmdb", "host", "boom")
    assert failed["result"] is False
    assert "db down" in failed["message"]


def test_save_operation_log_rejects_invalid_action_and_writes_valid():
    invalid = nats_api.save_operation_log("alice", "127.0.0.1", "cmdb", "explode")
    assert invalid["result"] is False

    ok = nats_api.save_operation_log(
        "alice",
        "127.0.0.1",
        "cmdb",
        OperationLog.ACTION_CREATE,
        summary="created host",
        target_type="host",
        target_id="1",
        detail={"id": 1},
    )
    assert ok["result"] is True
    log = OperationLog.objects.get(username="alice", summary="created host")
    assert log.action_type == OperationLog.ACTION_CREATE
    assert log.detail == {"id": 1}


def test_get_login_expired_seconds_uses_setting_or_default():
    assert nats_api._get_login_expired_seconds() == 3600 * 24
    SystemSettings.objects.create(key="login_expired_time", value="2")
    assert nats_api._get_login_expired_seconds() == 7200


def test_build_jwt_payload_contains_jti_and_exp():
    payload = nats_api._build_jwt_payload(42)
    assert payload["user_id"] == 42
    assert payload["jti"]
    assert payload["exp"] > payload["login_time"]
