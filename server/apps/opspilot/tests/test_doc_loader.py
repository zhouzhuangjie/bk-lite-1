"""DocLoader：加载失败返回空、全文/段落模式、表格转 Markdown、OCR 图片。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.metis.llm.loader.doc_loader import DocLoader

pytestmark = pytest.mark.unit


def test_doc_loader_file_error_returns_empty():
    with patch("apps.opspilot.metis.llm.loader.doc_loader.docx.Document", side_effect=OSError("bad")):
        assert DocLoader("/tmp/x.docx", ocr=None).load() == []


def test_doc_loader_full_paragraph_table_and_ocr():
    heading = SimpleNamespace(text="Title", style=SimpleNamespace(name="Heading 1"))
    body = SimpleNamespace(text="body text", style=SimpleNamespace(name="Normal"))
    row = SimpleNamespace(cells=[SimpleNamespace(text="a"), SimpleNamespace(text="b")])
    table = SimpleNamespace(rows=[row])
    image_rel = SimpleNamespace(target_ref="word/media/image1.png", target_part=SimpleNamespace(blob=b"img"))
    document = SimpleNamespace(
        paragraphs=[heading, body],
        tables=[table],
        part=SimpleNamespace(rels={"r1": image_rel}),
    )
    ocr = SimpleNamespace(predict=lambda path: "ocr-text")
    with patch("apps.opspilot.metis.llm.loader.doc_loader.docx.Document", return_value=document), patch(
        "apps.opspilot.metis.llm.loader.doc_loader.tqdm",
        side_effect=lambda it, desc=None: it,
    ):
        full_docs = DocLoader("/tmp/a.docx", ocr=ocr, mode="full").load()
        para_docs = DocLoader("/tmp/a.docx", ocr=None, mode="paragraph").load()
        unknown = DocLoader("/tmp/a.docx", ocr=None, mode="other").load()

    assert unknown == []
    assert any("Title" in d.page_content and "body text" in d.page_content for d in full_docs)
    assert any(d.metadata.get("format") == "table" and "| a | b |" in d.page_content for d in full_docs)
    assert any(d.metadata.get("format") == "image" and d.page_content == "ocr-text" for d in full_docs)
    assert para_docs[0].page_content.startswith("Title")
    assert "body text" in para_docs[0].page_content
