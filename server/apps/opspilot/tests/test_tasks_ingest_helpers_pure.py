"""opspilot.tasks 摄取参数、文件摄取临时文件清理、记忆追加。

对照知识训练契约：OCR/嵌入参数从模型配置组装；文件摄取结束后删除临时文件；记忆追加保留原文。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.opspilot import tasks

pytestmark = pytest.mark.unit


def test_prepare_ingest_params_includes_embed_semantic_and_azure_ocr():
    embed_model = SimpleNamespace(base_url="http://embed", api_key="ek", model_name="embed-v1")
    semantic_model = SimpleNamespace(base_url="http://sem", api_key="", model_name="sem-v1")
    ocr_model = SimpleNamespace(
        runtime_ocr_config={
            "ocr_type": "azure_ocr",
            "endpoint": "http://azure",
            "api_key": "ok",
            "model": "azure-1",
        }
    )
    document = SimpleNamespace(
        id=9,
        knowledge_base=SimpleNamespace(embed_model=embed_model),
        semantic_chunk_parse_embedding_model=semantic_model,
        enable_ocr_parse=True,
        ocr_model=ocr_model,
        chunk_type="full",
        general_parse_chunk_size=512,
        general_parse_chunk_overlap=64,
        mode="balanced",
        knowledge_index_name=lambda: "kb_index",
    )

    params = tasks._prepare_ingest_params(document, is_preview=True)
    assert params["is_preview"] is True
    assert params["knowledge_base_id"] == "kb_index"
    assert params["embed_model_name"] == "embed-v1"
    assert params["semantic_chunk_model"] == "sem-v1"
    assert params["semantic_chunk_model_api_key"] == " "
    assert params["ocr_type"] == "azure_ocr"
    assert params["olm_base_url"] == "http://azure"
    assert params["chunk_size"] == 512


def test_handle_file_ingest_writes_tempfile_then_deletes_it(tmp_path, monkeypatch):
    chunks = [b"hello ", b"world"]
    knowledge = SimpleNamespace(
        file=SimpleNamespace(name="doc.txt", chunks=lambda: iter(chunks)),
    )
    document = SimpleNamespace(id=3, fileknowledge_set=SimpleNamespace(all=lambda: [knowledge]))
    rag = MagicMock()
    rag.file_ingest.return_value = {"status": "success"}

    result = tasks._handle_file_ingest(document, {"k": 1}, rag)
    assert result == {"status": "success"}
    called_path = rag.file_ingest.call_args.kwargs["file_path"]
    assert called_path.endswith(".txt")
    assert not __import__("os").path.exists(called_path)
    assert rag.file_ingest.call_args.kwargs["file_name"] == "doc.txt"


def test_handle_file_ingest_missing_file_raises():
    document = SimpleNamespace(id=8, fileknowledge_set=SimpleNamespace(all=lambda: []))
    with pytest.raises(ValueError, match="找不到文件知识记录"):
        tasks._handle_file_ingest(document, {}, MagicMock())


def test_build_qa_item_params_and_ingest_single_item_skip_empty():
    base = {"metadata": {"is_doc": "0"}}
    assert tasks._build_qa_item_params({"instruction": "", "output": "a"}, base, {}) is None
    params = tasks._build_qa_item_params({"instruction": "Q", "output": "A"}, {"keep": 1}, {"is_doc": "0"})
    assert params["keep"] == 1
    assert params["metadata"]["qa_question"] == "Q"
    assert params["metadata"]["qa_answer"] == "A"

    rag = MagicMock()
    rag.custom_content_ingest.return_value = {"status": "success"}
    assert tasks._ingest_single_qa_item({"instruction": "", "output": "A"}, 0, {}, {}, rag) is None
    assert tasks._ingest_single_qa_item({"instruction": "Q", "output": "A"}, 1, {"x": 1}, {}, rag) is True
    rag.custom_content_ingest.return_value = {"status": "failed", "message": "nope"}
    assert tasks._ingest_qa_once("Q", {}, rag, 2) is False
    rag.custom_content_ingest.side_effect = RuntimeError("down")
    assert tasks._ingest_qa_once("Q", {}, rag, 3) is False


def test_append_memory_keeps_previous_content():
    memory = SimpleNamespace(content="old", updated_by="", save=MagicMock())
    tasks._append_memory(memory, "new-note", "alice")
    assert memory.content.startswith("old")
    assert "new-note" in memory.content
    assert memory.updated_by == "alice"
    memory.save.assert_called_once()
