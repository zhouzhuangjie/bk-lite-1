"""ExcelLoader：读取策略降级、三种 mode、表头/全文解析。"""
from unittest.mock import patch

import pandas as pd
import pytest
from langchain_core.documents import Document

from apps.opspilot.metis.llm.loader.excel_loader import ExcelLoader

pytestmark = pytest.mark.unit


def _sheets():
    df = pd.DataFrame({"col": ["a", None], "empty": [None, None], "n": [1, 2]})
    return {"Sheet1": df}


def test_safe_read_excel_falls_back_then_raises():
    loader = ExcelLoader("/tmp/demo.xlsx")
    df = pd.DataFrame({"a": [1]})
    with patch("apps.opspilot.metis.llm.loader.excel_loader.pd.read_excel", side_effect=[RuntimeError("openpyxl-fast"), df]) as read:
        out = loader._safe_read_excel(sheet_name=None)
    assert out is df
    assert read.call_count == 2

    with patch("apps.opspilot.metis.llm.loader.excel_loader.pd.read_excel", side_effect=ValueError("bad xlsx")):
        with pytest.raises(ValueError, match="所有读取策略均失败，文件: /tmp/demo.xlsx"):
            loader._safe_read_excel()


def test_dataframe_to_excel_format_string_drops_empty_and_nan():
    loader = ExcelLoader("/tmp/demo.xlsx")
    df = pd.DataFrame({"A": ["x", None], "B": [None, None], "C": [1, 2]})
    text = loader.dataframe_to_excel_format_string(df)
    assert "C" in text
    assert "nan" not in text
    assert "x" in text


def test_title_row_and_full_content_parse_and_load_modes():
    loader = ExcelLoader("/tmp/demo.xlsx", mode="excel_header_row_parse")
    with patch.object(loader, "_safe_read_excel", return_value=_sheets()):
        rows = loader.title_row_struct_load()
    assert len(rows) == 2
    assert all(isinstance(d, Document) for d in rows)
    assert rows[0].metadata == {"format": "table", "sheet": "Sheet1"}
    assert "Sheet1  col:" in rows[0].page_content

    loader.mode = "excel_full_content_parse"
    with patch.object(loader, "_safe_read_excel", return_value=_sheets()):
        docs = loader.excel_full_content_parse_load()
    assert len(docs) == 1
    assert docs[0].metadata["source"] == "/tmp/demo.xlsx"
    assert docs[0].metadata["format"] == "table"
    assert "a" in docs[0].page_content
    assert "1" in docs[0].page_content

    loader.mode = "full"
    with patch.object(loader, "_safe_read_excel", return_value=_sheets()):
        all_docs = loader.load()
    assert len(all_docs) == 1
    assert all_docs[0].metadata["sheets"] == ["Sheet1"]
    assert all_docs[0].page_content.startswith("Sheet1")

    with patch.object(loader, "title_row_struct_load", return_value=["t"]) as title:
        loader.mode = "excel_header_row_parse"
        assert loader.load() == ["t"]
        title.assert_called_once()
    with patch.object(loader, "excel_full_content_parse_load", return_value=["f"]) as full:
        loader.mode = "excel_full_content_parse"
        assert loader.load() == ["f"]
        full.assert_called_once()

    loader.mode = "unknown"
    with pytest.raises(ValueError, match="Unsupported mode: unknown"):
        loader.load()
