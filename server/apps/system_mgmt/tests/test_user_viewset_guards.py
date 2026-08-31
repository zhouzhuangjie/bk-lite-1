"""UserViewSet 静态守卫：禁用 CRUD、电话校验、状态跳过原因、ID 规范化。"""
import json
from types import SimpleNamespace

import pytest

from apps.system_mgmt.viewset.user_viewset import UserViewSet

pytestmark = pytest.mark.unit


def test_builtin_crud_disabled():
    view = UserViewSet()
    req = SimpleNamespace()
    for method in ("list", "retrieve", "create", "update", "partial_update", "destroy"):
        resp = getattr(view, method)(req, pk=1)
        assert resp.status_code == 405
        assert json.loads(resp.content)["result"] is False


def test_is_valid_phone_accepts_empty_and_international():
    assert UserViewSet._is_valid_phone(None) is True
    assert UserViewSet._is_valid_phone("") is True
    assert UserViewSet._is_valid_phone("  ") is True
    assert UserViewSet._is_valid_phone("+86 138-0013-8000") is True
    assert UserViewSet._is_valid_phone("123") is False
    assert UserViewSet._is_valid_phone("abc1234567") is False
    assert UserViewSet._is_valid_phone(13800138000) is False


def test_normalize_user_ids_collects_invalid():
    normalized, invalid = UserViewSet._normalize_user_ids(["1", 2, "x", None])
    assert normalized == [1, 2]
    assert "x" in invalid
    assert None in invalid
    assert UserViewSet._normalize_user_ids(None) == ([], [])


def test_change_status_skip_reason():
    enabled = SimpleNamespace(disabled=False)
    disabled = SimpleNamespace(disabled=True)
    assert UserViewSet._get_change_status_skip_reason("enable", enabled, now=None) == "user_not_disabled"
    assert UserViewSet._get_change_status_skip_reason("enable", disabled, now=None) is None
    assert UserViewSet._get_change_status_skip_reason("disable", enabled, now=None) is None
    assert UserViewSet._get_change_status_skip_reason("disable", disabled, now=None) == "user_not_enabled"
    assert UserViewSet._get_change_status_skip_reason("noop", enabled, now=None) == "invalid_action"


def test_mask_payload_passthrough_when_ee_missing(monkeypatch):
    req = SimpleNamespace(user=SimpleNamespace())
    data = {"username": "alice"}
    monkeypatch.setattr("apps.system_mgmt.viewset.user_viewset.apply_sensitive_info_mask", None)
    monkeypatch.setattr("apps.system_mgmt.viewset.user_viewset.apply_sensitive_info_mask_to_list", None)
    assert UserViewSet._mask_user_payload(data, req) is data
    assert UserViewSet._mask_user_payload_list([data], req) == [data]
