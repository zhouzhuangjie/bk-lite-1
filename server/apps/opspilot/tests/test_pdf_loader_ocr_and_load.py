"""PDFLoader：OCR 图片解析、表格成功路径与 load 文本异常吞掉。"""
from unittest.mock import MagicMock

import pandas as pd
import pytest
from langchain_core.documents import Document

from apps.opspilot.metis.llm.loader.pdf_loader import PDFLoader

pytestmark = pytest.mark.unit


def _loader(ocr, tmp_path, mode="full"):
    return PDFLoader(str(tmp_path / "doc.pdf"), ocr=ocr, load_mode=mode)


def test_parse_images_ocr_success_failure_and_unlink_warning(tmp_path, monkeypatch):
    monkeypatch.setattr("apps.opspilot.metis.llm.loader.pdf_loader.tqdm", lambda it, **k: it)
    ocr = MagicMock()
    ocr.predict.return_value = "ocr-text"
    loader = _loader(ocr, tmp_path)

    page = MagicMock()
    page.get_images.return_value = [(7,)]
    pdf = MagicMock()
    pdf.__len__.return_value = 1
    pdf.__getitem__.return_value = page
    pdf.extract_image.return_value = {"image": b"png-bytes"}

    unlinked = []

    def _unlink(path):
        unlinked.append(path)

    monkeypatch.setattr("os.unlink", _unlink)
    docs = loader._parse_images(pdf)
    assert len(docs) == 1
    assert docs[0].page_content == "ocr-text"
    assert docs[0].metadata["format"] == "image"
    assert docs[0].metadata["page"] == 1
    assert docs[0].metadata["image_base64"]
    assert len(unlinked) == 1
    ocr.predict.assert_called_once_with(unlinked[0])

    ocr.predict.side_effect = RuntimeError("ocr-down")
    unlinked.clear()
    docs = loader._parse_images(pdf)
    assert docs == []
    assert len(unlinked) == 1

    def _unlink_fail(path):
        raise OSError("busy")

    monkeypatch.setattr("os.unlink", _unlink_fail)
    docs = loader._parse_images(pdf)
    assert docs == []


def test_parse_tables_markdown_and_page_number(tmp_path, monkeypatch):
    loader = _loader(None, tmp_path)
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4 dummy")
    table = pd.DataFrame({"col": ["v1"]})
    pages = [{"page_number": 3}]

    def _read_pdf(*args, **kwargs):
        if kwargs.get("output_format") == "json":
            return pages
        return [table]

    monkeypatch.setattr("apps.opspilot.metis.llm.loader.pdf_loader.read_pdf", _read_pdf)
    docs = loader._parse_tables()
    assert len(docs) == 1
    assert docs[0].metadata == {"format": "table", "page": 3}
    assert "v1" in docs[0].page_content
    assert "col" in docs[0].page_content


def test_load_swallows_text_error_and_keeps_table_docs(tmp_path, monkeypatch):
    monkeypatch.setattr("apps.opspilot.metis.llm.loader.pdf_loader.tqdm", lambda it, **k: it)
    loader = _loader(None, tmp_path, mode="full")
    table_doc = Document("tbl", metadata={"format": "table", "page": 1})

    class BoomPdf:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            raise RuntimeError("text-boom")

    monkeypatch.setattr("apps.opspilot.metis.llm.loader.pdf_loader.fitz.open", lambda *a, **k: BoomPdf())
    monkeypatch.setattr(loader, "_parse_images", lambda pdf: [])
    monkeypatch.setattr(loader, "_get_table_areas", lambda pdf: [])
    monkeypatch.setattr(loader, "_parse_tables", lambda: [table_doc])
    docs = loader.load()
    assert docs == [table_doc]

    loader.load_mode = "page"

    class PageBoomPdf(BoomPdf):
        def __iter__(self):
            page = MagicMock()
            page.number = 0
            yield page

    monkeypatch.setattr("apps.opspilot.metis.llm.loader.pdf_loader.fitz.open", lambda *a, **k: PageBoomPdf())
    monkeypatch.setattr(loader, "_extract_page_text", lambda page, areas: (_ for _ in ()).throw(RuntimeError("page-boom")))
    docs = loader.load()
    assert docs == [table_doc]
