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
