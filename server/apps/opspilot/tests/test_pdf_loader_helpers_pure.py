"""PDFLoader：表格区域重叠判断、unicode 清理、无 OCR 跳过图片。"""
from types import SimpleNamespace

import pytest

from apps.opspilot.metis.llm.loader.pdf_loader import PDFLoader

pytestmark = pytest.mark.unit


def test_remove_unicode_and_table_area_overlap():
    loader = PDFLoader("/tmp/a.pdf", ocr=None)
    assert loader.remove_unicode_chars("hello\\uf0b7world") == "helloworld"
    areas = [(0, (10, 10, 50, 50))]
    assert loader._is_in_table_area(0, (20, 20, 30, 30), areas) is True
    assert loader._is_in_table_area(0, (80, 80, 90, 90), areas) is False
    assert loader._is_in_table_area(1, (20, 20, 30, 30), areas) is False
    assert loader._is_in_table_area(0, None, areas) is False


def test_extract_page_text_skips_table_blocks():
    loader = PDFLoader("/tmp/a.pdf", ocr=None)
    page = SimpleNamespace(
        number=0,
        get_text=lambda mode: {
            "blocks": [
                {"type": 0, "bbox": (1, 1, 2, 2), "lines": [{"spans": [{"text": "keep"}]}]},
                {"type": 0, "bbox": (15, 15, 20, 20), "lines": [{"spans": [{"text": "table"}]}]},
                {"type": 1, "bbox": (1, 1, 2, 2), "lines": []},
            ]
        },
    )
    text = loader._extract_page_text(page, [(0, (10, 10, 50, 50))])
    assert "keep" in text
    assert "table" not in text


def test_parse_images_skips_without_ocr():
    loader = PDFLoader("/tmp/a.pdf", ocr=None)
    assert loader._parse_images([SimpleNamespace()]) == []
