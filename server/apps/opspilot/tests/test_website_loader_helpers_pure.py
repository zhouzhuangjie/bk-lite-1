"""WebSiteLoader：图片 URL 合法性与下载失败 fail-closed。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.core.utils.safe_requests import SafeRequestsError
from apps.opspilot.metis.llm.loader.website_loader import WebSiteLoader

pytestmark = pytest.mark.unit


def test_is_valid_image_url():
    assert WebSiteLoader._is_valid_image_url("https://cdn.example.com/a.png") is True
    assert WebSiteLoader._is_valid_image_url("/relative.png") is False
    assert WebSiteLoader._is_valid_image_url("") is False


def test_download_image_rejects_non_image_and_oversize():
    bad_status = SimpleNamespace(status_code=404, headers={}, content=b"")
    with patch("apps.opspilot.metis.llm.loader.website_loader.safe_get", return_value=bad_status):
        assert WebSiteLoader._download_image("https://x/a.png") is None
    not_image = SimpleNamespace(status_code=200, headers={"content-type": "text/html"}, content=b"<html>")
    with patch("apps.opspilot.metis.llm.loader.website_loader.safe_get", return_value=not_image):
        assert WebSiteLoader._download_image("https://x/a.png") is None
    huge = SimpleNamespace(status_code=200, headers={"content-type": "image/png"}, content=b"x" * 20)
    with patch("apps.opspilot.metis.llm.loader.website_loader.safe_get", return_value=huge):
        assert WebSiteLoader._download_image("https://x/a.png", max_size=10) is None
    ok = SimpleNamespace(status_code=200, headers={"content-type": "image/png"}, content=b"img")
    with patch("apps.opspilot.metis.llm.loader.website_loader.safe_get", return_value=ok):
        assert WebSiteLoader._download_image("https://x/a.png") == b"img"
    with patch("apps.opspilot.metis.llm.loader.website_loader.safe_get", side_effect=SafeRequestsError("ssrf")):
        assert WebSiteLoader._download_image("https://x/a.png") is None
