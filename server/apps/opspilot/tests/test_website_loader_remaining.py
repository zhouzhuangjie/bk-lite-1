"""WebSiteLoader：SSRF 校验、图片下载过滤、OCR 识别与临时文件清理。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from apps.core.utils.safe_requests import SafeRequestsError
from apps.core.utils.ssrf_validator import SSRFError
from apps.opspilot.metis.llm.loader.website_loader import WebSiteLoader

pytestmark = pytest.mark.unit
MOD = "apps.opspilot.metis.llm.loader.website_loader"


def test_is_valid_image_url_requires_scheme_and_host():
    assert WebSiteLoader._is_valid_image_url("https://cdn.example.com/a.png") is True
    assert WebSiteLoader._is_valid_image_url("/relative.png") is False
    with patch(f"{MOD}.urlparse", side_effect=ValueError("bad")):
        assert WebSiteLoader._is_valid_image_url("https://x") is False


def test_download_image_filters_status_type_size_and_ssrf():
    url = "https://cdn.example.com/a.png"
    with patch(f"{MOD}.safe_get", return_value=SimpleNamespace(status_code=404, headers={}, content=b"")):
        assert WebSiteLoader._download_image(url) is None
    with patch(
        f"{MOD}.safe_get",
        return_value=SimpleNamespace(status_code=200, headers={"content-type": "text/html"}, content=b"x"),
    ):
        assert WebSiteLoader._download_image(url) is None
    with patch(
        f"{MOD}.safe_get",
        return_value=SimpleNamespace(status_code=200, headers={"content-type": "image/png"}, content=b"x" * 20),
    ):
        assert WebSiteLoader._download_image(url, max_size=10) is None
    with patch(f"{MOD}.safe_get", side_effect=SSRFError("blocked")):
        assert WebSiteLoader._download_image(url) is None
    with patch(f"{MOD}.safe_get", side_effect=SafeRequestsError("timeout")):
        assert WebSiteLoader._download_image(url) is None
    with patch(f"{MOD}.safe_get", side_effect=RuntimeError("boom")):
        assert WebSiteLoader._download_image(url) is None
    body = b"img-bytes"
    with patch(
        f"{MOD}.safe_get",
        return_value=SimpleNamespace(status_code=200, headers={"content-type": "image/jpeg"}, content=body),
    ):
        assert WebSiteLoader._download_image(url) == body


def test_process_image_tag_skips_invalid_and_uses_ocr_methods(tmp_path):
    loader = WebSiteLoader("https://example.com", 1, ocr=SimpleNamespace(predict_from_base64=lambda b64: "from-b64"))
    assert loader._process_image_tag(SimpleNamespace(get=lambda k, default=None: None), "https://example.com", 1) is None

    data_tag = MagicMock()
    data_tag.get.side_effect = lambda k, default="": "data:image/png;base64,xx" if k == "src" else default
    assert loader._process_image_tag(data_tag, "https://example.com", 1) is None

    tag = MagicMock()
    tag.get.side_effect = lambda k, default="": {"src": "/a.png", "alt": "logo", "title": "t"}.get(k, default)
    with patch.object(WebSiteLoader, "_download_image", return_value=b"png"):
        doc = loader._process_image_tag(tag, "https://example.com/page", 2)
    assert doc.metadata["format"] == "image"
    assert "图片描述(alt): logo" in doc.page_content
    assert "from-b64" in doc.page_content

    file_ocr = SimpleNamespace(predict=lambda path: f"file:{path}")
    loader.ocr = file_ocr
    with patch.object(WebSiteLoader, "_download_image", return_value=b"png"):
        doc = loader._process_image_tag(tag, "https://example.com/page", 3)
    assert "图片OCR识别内容:" in doc.page_content
    assert "file:" in doc.page_content

    loader.ocr = SimpleNamespace(predict_from_base64=lambda b64: (_ for _ in ()).throw(RuntimeError("ocr down")))
    with patch.object(WebSiteLoader, "_download_image", return_value=b"png"):
        assert loader._process_image_tag(tag, "https://example.com/page", 4) is None


def test_extract_images_and_load_merges_text_and_ocr_docs():
    html = '<html><body><img src="https://cdn.example.com/a.png"/></body></html>'
    web_docs = [Document(page_content=html, metadata={"source": "https://example.com"})]
    loader = WebSiteLoader("https://example.com", 2, ocr=SimpleNamespace(predict_from_base64=lambda b64: "ocr"))
    with patch.object(WebSiteLoader, "_download_image", return_value=b"png"):
        images = loader._extract_images_from_pages(web_docs)
    assert len(images) == 1

    broken = WebSiteLoader("https://example.com", 1, ocr=object())
    with patch(f"{MOD}.BeautifulSoup", side_effect=RuntimeError("parse")):
        assert broken._extract_images_from_pages(web_docs) == []

    text_docs = [Document(page_content="hello", metadata={})]
    with (
        patch(f"{MOD}.SSRFValidator.validate", return_value="https://example.com") as validate,
        patch(f"{MOD}.RecursiveUrlLoader") as loader_cls,
        patch(f"{MOD}.BeautifulSoupTransformer") as trans_cls,
        patch.object(WebSiteLoader, "_extract_images_from_pages", return_value=images) as extract,
    ):
        loader_cls.return_value.load.return_value = web_docs
        trans_cls.return_value.transform_documents.return_value = text_docs
        out = loader.load()
    validate.assert_called_once_with("https://example.com")
    extract.assert_called_once()
    assert out == text_docs + images

    no_ocr = WebSiteLoader("https://example.com", 1, ocr=None)
    with (
        patch(f"{MOD}.SSRFValidator.validate", return_value="https://example.com"),
        patch(f"{MOD}.RecursiveUrlLoader") as loader_cls,
        patch(f"{MOD}.BeautifulSoupTransformer") as trans_cls,
        patch.object(WebSiteLoader, "_extract_images_from_pages") as extract,
    ):
        loader_cls.return_value.load.return_value = web_docs
        trans_cls.return_value.transform_documents.return_value = text_docs
        out = no_ocr.load()
    extract.assert_not_called()
    assert out == text_docs
