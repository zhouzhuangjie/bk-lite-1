"""Fetch 工具纯函数：配置、URL、截断、HTML 清理与编码解析。"""
from unittest.mock import patch

import pytest

from apps.core.utils.ssrf_validator import SSRFError
from apps.opspilot.metis.llm.tools.fetch.utils import (
    clean_html_tags,
    format_error_response,
    format_response_info,
    is_valid_json_content_type,
    parse_content_type_encoding,
    prepare_fetch_config,
    prepare_headers,
    truncate_content,
    validate_url,
)

pytestmark = pytest.mark.unit


def test_prepare_fetch_config_and_headers():
    assert prepare_fetch_config()["timeout"] == 30
    cfg = prepare_fetch_config(
        {"configurable": {"default_timeout": 9, "default_limit": 12, "user_agent": "ua", "verify_ssl": False}}
    )
    assert cfg == {"timeout": 9, "default_limit": 12, "user_agent": "ua", "verify_ssl": False}
    assert prepare_headers(None, None) == {}
    assert prepare_headers({"X": "1"}, "ua") == {"User-Agent": "ua", "X": "1"}


def test_validate_url_adds_https_and_rejects_empty_or_ssrf():
    with pytest.raises(ValueError, match="URL不能为空"):
        validate_url("  ")
    with pytest.raises(ValueError, match="URL格式无效"):
        validate_url("https://")
    with patch(
        "apps.opspilot.metis.llm.tools.fetch.utils.SSRFValidator.validate",
        side_effect=SSRFError("blocked"),
    ):
        with pytest.raises(SSRFError, match="blocked"):
            validate_url("http://127.0.0.1/secret")
    with patch("apps.opspilot.metis.llm.tools.fetch.utils.SSRFValidator.validate"):
        assert validate_url("example.com/a") == "https://example.com/a"


def test_truncate_and_response_helpers():
    assert truncate_content("abc", start_index=9)["content"] == ""
    full = truncate_content("abcdef", max_length=None, start_index=2)
    assert full == {
        "content": "cdef",
        "total_length": 6,
        "truncated": False,
        "start_index": 2,
        "end_index": 6,
        "remaining": 0,
    }
    cut = truncate_content("abcdef", max_length=2, start_index=1)
    assert cut["content"] == "bc"
    assert cut["truncated"] is True
    assert cut["remaining"] == 3
    assert format_response_info(200, {"Content-Type": "text/plain"}, 4)["content_type"] == "text/plain"
    cleaned = clean_html_tags("<script>x</script><b>hi</b>&nbsp;&amp;")
    assert cleaned == "hi &"
    assert is_valid_json_content_type("application/json; charset=utf-8") is True
    assert is_valid_json_content_type("") is False
    assert parse_content_type_encoding('text/html; charset="utf-8"') == "utf-8"
    assert parse_content_type_encoding("text/html") is None
    err = format_error_response(ValueError("boom"), "https://x")
    assert err == {"success": False, "error": "boom", "error_type": "ValueError", "url": "https://x"}
    neg = truncate_content("ab", start_index=-3)
    assert neg["content"] == "ab"
    assert neg["truncated"] is False
    assert parse_content_type_encoding("") is None
    assert parse_content_type_encoding("text/plain; charset=gbk") == "gbk"
    assert parse_content_type_encoding("text/plain; boundary=x") is None
    assert is_valid_json_content_type("application/vnd.api+json") is True
