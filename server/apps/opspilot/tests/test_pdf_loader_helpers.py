"""PDFLoader：表格区域检测、文本提取跳过表格、无 OCR 跳过图片、表格解析失败。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.opspilot.metis.llm.loader.pdf_loader import PDFLoader

pytestmark = pytest.mark.unit


def test_table_area_and_page_text_skip_and_errors(monkeypatch):
    loader = PDFLoader("/tmp/a.pdf", ocr=None, load_mode="full")
    monkeypatch.setattr("apps.opspilot.metis.llm.loader.pdf_loader.tqdm", lambda it, **k: it)

    table = SimpleNamespace(bbox=(0, 0, 50, 50))
    tables = SimpleNamespace(tables=[table])
    page = MagicMock()
    page.number = 0
    page.find_tables.return_value = tables
    page.get_text.return_value = {
        "blocks": [
            {"type": 0, "bbox": (1, 1, 10, 10), "lines": [{"spans": [{"text": "in-table"}]}]},
            {"type": 0, "bbox": (80, 80, 90, 90), "lines": [{"spans": [{"text": "outside\\uf000"}]}]},
            {"type": 1, "bbox": (0, 0, 1, 1), "lines": []},
        ]
    }
    areas = loader._get_table_areas([page])
    assert areas == [(0, (0, 0, 50, 50))]
    assert loader._is_in_table_area(0, (1, 1, 10, 10), areas) is True
    assert loader._is_in_table_area(0, (80, 80, 90, 90), areas) is False
    assert loader._is_in_table_area(0, "bad", areas) is False

    text = loader._extract_page_text(page, areas)
    assert text == "outside"
    assert "in-table" not in text

    page.get_text.side_effect = RuntimeError("broken")
    assert loader._extract_page_text(page, areas) == ""

    assert loader._parse_images([page]) == []
    assert loader._parse_tables() == []
