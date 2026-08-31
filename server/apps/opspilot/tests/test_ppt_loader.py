"""PPTLoader：全文/分页抽取文本框与表格，OCR 走 base64 路径。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.documents import Document

from apps.opspilot.metis.llm.loader.ppt_loader import PPTLoader

pytestmark = pytest.mark.unit


class _Frame:
    def __init__(self, text):
        self.paragraphs = [SimpleNamespace(text=text)]


class _Cell:
    def __init__(self, text):
        self.text_frame = _Frame(text)


class _Row:
    def __init__(self, cells):
        self.cells = cells


class _Table:
    def __init__(self, rows):
        self.rows = rows


class _Shape:
    def __init__(self, *, text=None, table=None, picture=None):
        self.has_text_frame = text is not None
        self.text_frame = _Frame(text) if text is not None else None
        self.has_table = table is not None
        self.table = table
        self.shape_type = 13 if picture is not None else 1
        if picture is not None:
            self.image = SimpleNamespace(blob=picture)


class _Slide:
    def __init__(self, shapes):
        self.shapes = shapes


def test_ppt_loader_full_and_page_modes_and_ocr():
    table = _Table([_Row([_Cell("c1"), _Cell("c2")])])
    slides = [
        _Slide(
            [
                _Shape(text="hello"),
                _Shape(table=table),
                _Shape(picture=b"img-bytes"),
            ]
        )
    ]
    ocr = SimpleNamespace(predict_from_base64=lambda data: f"ocr:{data[:4]}")
    with patch("apps.opspilot.metis.llm.loader.ppt_loader.Presentation") as prs, patch(
        "apps.opspilot.metis.llm.loader.ppt_loader.tqdm",
        side_effect=lambda it, desc=None: it,
    ):
        prs.return_value.slides = slides
        docs = PPTLoader("/tmp/a.pptx", ocr, "full").load()
    texts = [d.page_content for d in docs]
    assert any("c1" in t and "c2" in t for t in texts)
    assert any(d.metadata.get("format") == "table" for d in docs)
    image_docs = [d for d in docs if d.metadata.get("format") == "image"]
    assert len(image_docs) == 1
    assert image_docs[0].page_content.startswith("ocr:")
    assert any(isinstance(d, Document) and "hello" in d.page_content for d in docs)

    with patch("apps.opspilot.metis.llm.loader.ppt_loader.Presentation") as prs, patch(
        "apps.opspilot.metis.llm.loader.ppt_loader.tqdm",
        side_effect=lambda it, desc=None: it,
    ):
        prs.return_value.slides = [_Slide([_Shape(text="page-one")])]
        page_docs = PPTLoader("/tmp/b.pptx", None, "page").load()
    assert page_docs[0].page_content == "page-one"
    assert page_docs[0].metadata["slide_number"] == 1
