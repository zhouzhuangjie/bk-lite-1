"""Fetch HTTP：成功响应字段、Bearer、超时/HTTP 错误包装。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from apps.opspilot.metis.llm.tools.fetch import http as h

pytestmark = pytest.mark.unit


def test_http_get_success_sets_bearer_and_fields():
    resp = SimpleNamespace(
        status_code=200,
        text="<ok>",
        headers={"Content-Type": "text/html; charset=utf-8"},
        url="https://example.com/final",
        encoding="utf-8",
        raise_for_status=lambda: None,
    )
    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_get", return_value=resp) as get,
    ):
        out = h._http_get_impl("https://example.com", bearer_token="tok", timeout="9")
    assert out["success"] is True
    assert out["content"] == "<ok>"
    assert out["url"] == "https://example.com/final"
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
    assert get.call_args.kwargs["timeout"] == 9


def test_http_get_maps_timeout_and_http_error():
    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_get", side_effect=requests.exceptions.Timeout()),
    ):
        out = h._http_get_impl("https://example.com")
    assert out["success"] is False
    assert "超时" in out["error"]

    err = requests.exceptions.HTTPError("404")
    err.response = SimpleNamespace(status_code=404)
    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_get", side_effect=err),
    ):
        http_err = h._http_get_impl("https://example.com")
    assert http_err["status_code"] == 404
    assert http_err["success"] is False


def _resp(text="ok", status_code=200, content_type="application/json"):
    return SimpleNamespace(
        status_code=status_code,
        text=text,
        headers={"Content-Type": content_type},
        url="https://example.com/final",
        encoding="utf-8",
        raise_for_status=lambda: None,
    )


def test_http_get_ssl_error_and_invalid_timeout_uses_default():
    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_get", side_effect=requests.exceptions.SSLError("bad-cert")),
    ):
        ssl_err = h._http_get_impl("https://example.com")
    assert ssl_err["success"] is False
    assert "SSL" in ssl_err["error"]

    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_get", return_value=_resp()) as get,
    ):
        out = h._http_get_impl("https://example.com", timeout="not-a-number")
    assert out["success"] is True
    assert get.call_args.kwargs["timeout"] == 30


def test_http_post_put_delete_patch_success_and_errors():
    ok = _resp('{"ok": true}')
    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_post", return_value=ok) as post,
    ):
        out = h._http_post_impl("https://example.com", json_data={"a": 1}, bearer_token="tok", timeout="7")
    assert out["success"] is True
    assert out["content"] == '{"ok": true}'
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
    assert post.call_args.kwargs["timeout"] == 7
    assert post.call_args.kwargs["json"] == {"a": 1}

    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_put", return_value=ok),
    ):
        assert h._http_put_impl("https://example.com", data="x", bearer_token="t")["success"] is True

    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_delete", return_value=ok),
    ):
        assert h._http_delete_impl("https://example.com", bearer_token="t")["success"] is True

    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_patch", return_value=ok),
    ):
        assert h._http_patch_impl("https://example.com", json_data={"p": 1}, bearer_token="t")["success"] is True

    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_post", side_effect=requests.exceptions.Timeout()),
    ):
        timed = h._http_post_impl("https://example.com")
    assert timed["success"] is False
    assert "超时" in timed["error"]

    err = requests.exceptions.HTTPError("500")
    err.response = SimpleNamespace(status_code=500)
    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_put", side_effect=err),
    ):
        put_err = h._http_put_impl("https://example.com")
    assert put_err["success"] is False
    assert put_err["status_code"] == 500

    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_delete", side_effect=requests.exceptions.Timeout()),
    ):
        assert h._http_delete_impl("https://example.com")["success"] is False

    with (
        patch.object(h, "validate_url", side_effect=lambda u: u),
        patch.object(h, "safe_patch", side_effect=err),
    ):
        patch_err = h._http_patch_impl("https://example.com")
    assert patch_err["status_code"] == 500


def test_http_tool_wrappers_delegate_to_impl():
    with patch.object(h, "_http_get_impl", return_value={"success": True, "content": "g"}):
        assert h.http_get.invoke({"url": "https://example.com"})["content"] == "g"
    with patch.object(h, "_http_post_impl", return_value={"success": True, "content": "p"}):
        assert h.http_post.invoke({"url": "https://example.com"})["content"] == "p"
    with patch.object(h, "_http_put_impl", return_value={"success": True, "content": "u"}):
        assert h.http_put.invoke({"url": "https://example.com"})["content"] == "u"
    with patch.object(h, "_http_delete_impl", return_value={"success": True, "content": "d"}):
        assert h.http_delete.invoke({"url": "https://example.com"})["content"] == "d"
    with patch.object(h, "_http_patch_impl", return_value={"success": True, "content": "h"}):
        assert h.http_patch.invoke({"url": "https://example.com"})["content"] == "h"
