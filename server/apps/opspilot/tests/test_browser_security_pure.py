"""浏览器工具共享安全辅助：SSRF、敏感值脱敏、临时 profile 清理。"""
import os

import pytest

from apps.core.utils.ssrf_validator import SSRFError
from apps.opspilot.metis.llm.tools.common.browser_security import (
    MIN_SENSITIVE_VALUE_LEN,
    browser_user_data_dir,
    build_sensitive_data,
    collect_sensitive_values,
    is_safe_browser_url,
    redact_command_args,
    redact_secrets,
    validate_browser_url,
)

pytestmark = pytest.mark.unit


def test_validate_browser_url_rejects_empty():
    with pytest.raises(ValueError, match="URL 不能为空"):
        validate_browser_url("   ")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_validate_browser_url_blocks_ssrf_targets(url):
    with pytest.raises((ValueError, SSRFError)):
        validate_browser_url(url)
    assert is_safe_browser_url(url) is False


def test_validate_browser_url_accepts_public_https(mocker):
    mocker.patch(
        "apps.opspilot.metis.llm.tools.common.browser_security.SSRFValidator.validate",
        return_value="https://example.com/path",
    )
    assert validate_browser_url("  https://example.com/path  ") == "https://example.com/path"
    assert is_safe_browser_url("https://example.com/path") is True


def test_build_sensitive_data_skips_short_or_empty_values():
    assert build_sensitive_data(username="ab", password="12") is None
    assert build_sensitive_data(username="", password="") is None
    data = build_sensitive_data(username="admin01", password="s")
    assert data == {"x_username": "admin01"}
    assert MIN_SENSITIVE_VALUE_LEN == 4


def test_collect_sensitive_values_dedupes_and_prefers_longer():
    values = collect_sensitive_values("secret-token", "sec", "secret-token", None, "super-secret-token")
    assert values[0] == "super-secret-token"
    assert values.count("secret-token") == 1
    assert "sec" not in values


def test_redact_secrets_replaces_all_known_values():
    text = "user=admin01 password=hunter2 leftover"
    assert redact_secrets(text, ["admin01", "hunter2"]) == "user=*** password=*** leftover"
    assert redact_secrets("", ["x"]) == ""
    assert redact_secrets("plain", None) == "plain"


def test_redact_command_args_masks_type_fill_values_and_explicit_secrets():
    args = ["open", "https://admin01.example/login", "type", "hunter2", "click", "@btn"]
    redacted = redact_command_args(args, secret_values=["admin01"])
    assert redacted[0] == "open"
    assert redacted[1] == "https://***.example/login"
    assert redacted[3] == "***"
    assert redacted[5] == "@btn"
    assert redact_command_args(None) == []


def test_browser_user_data_dir_reuses_persistent_and_cleans_temp():
    with browser_user_data_dir("/persistent-profile") as path:
        assert path == "/persistent-profile"
    with browser_user_data_dir(None) as temp_dir:
        assert os.path.isdir(temp_dir)
        marker = os.path.join(temp_dir, "marker")
        open(marker, "w").write("x")
    assert not os.path.exists(temp_dir)
