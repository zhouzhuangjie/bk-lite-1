"""WebSiteLoader._process_image_tag：缺 src / data URL 跳过，成功 OCR 返回 Document。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.documents import Document

from apps.opspilot.metis.llm.loader.website_loader import WebSiteLoader

pytestmark = pytest.mark.unit


def test_process_image_tag_skips_invalid_and_ocr_success():
    ocr = SimpleNamespace(predict_from_base64=lambda data: "ocr-ok")
    loader = WebSiteLoader("https://example.com/page", max_depth=1, ocr=ocr)
    assert loader._process_image_tag(SimpleNamespace(get=lambda *a, **k: None), "https://example.com/page", 0) is None

    data_tag = SimpleNamespace(get=lambda key, default="": "data:image/png;base64,xxx" if key == "src" else default)
    assert loader._process_image_tag(data_tag, "https://example.com/page", 1) is None

    tag = SimpleNamespace(
        get=lambda key, default="": {"src": "/img/a.png", "alt": "logo", "title": "t"}.get(key, default)
    )
    with patch.object(loader, "_download_image", return_value=b"img-bytes"):
        doc = loader._process_image_tag(tag, "https://example.com/page", 2)
    assert isinstance(doc, Document)
    assert "ocr-ok" in doc.page_content
    assert "图片描述(alt): logo" in doc.page_content
    assert doc.metadata["format"] == "image"
    assert doc.metadata["page"] == 2
