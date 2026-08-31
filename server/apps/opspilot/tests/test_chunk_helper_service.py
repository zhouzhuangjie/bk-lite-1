"""ChunkHelper：文档检索/删除/问答对写入。仅 mock PgvectorRag 与 QAGeneration 外部边界。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from apps.opspilot.utils.chunk_helper import ChunkHelper

pytestmark = pytest.mark.unit


@pytest.fixture
def rag(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("apps.opspilot.utils.chunk_helper.PgvectorRag", lambda: client)
    return client


def test_get_document_es_chunk_returns_documents_and_count(rag):
    rag.list_index_document.return_value = [
        Document(page_content="hello", metadata={"chunk_id": "c1"}),
    ]
    rag.count_index_document.return_value = 3
    result = ChunkHelper.get_document_es_chunk("kb", page=2, page_size=10, search_text="hi")
    assert result["status"] == "success"
    assert result["count"] == 3
    assert result["documents"] == [{"page_content": "hello", "metadata": {"chunk_id": "c1"}}]
    request = rag.list_index_document.call_args.args[0]
    assert request.index_name == "kb"
    assert request.page == 2
    assert request.size == 10
    assert request.query == "hi"


def test_get_document_es_chunk_skips_count_when_disabled(rag):
    rag.list_index_document.return_value = []
    result = ChunkHelper.get_document_es_chunk("kb", get_count=False)
    assert result["count"] == 0
    rag.count_index_document.assert_not_called()


def test_delete_es_content_maps_chunk_and_knowledge_ids(rag):
    rag.delete_document.return_value = None
    assert ChunkHelper.delete_es_content(["a", "b"], is_chunk=True) is True
    req = rag.delete_document.call_args.args[0]
    assert req.chunk_ids == ["a", "b"]
    assert req.knowledge_ids == []

    assert ChunkHelper.delete_es_content(9, is_chunk=False, keep_qa=True) is True
    req = rag.delete_document.call_args.args[0]
    assert req.knowledge_ids == ["qa_pairs_id_9"]
    assert req.keep_qa is True

    rag.delete_document.side_effect = RuntimeError("down")
    assert ChunkHelper.delete_es_content("x", is_chunk=True) is False


def test_set_qa_pairs_params_fills_embed_and_metadata():
    kwargs, metadata = ChunkHelper.set_qa_pairs_params(
        {"base_url": "http://e", "api_key": "", "model": "m"},
        "idx",
        7,
        chunk_obj={"chunk_id": "c1"},
    )
    assert kwargs["knowledge_id"] == "qa_pairs_id_7"
    assert kwargs["embed_model_api_key"] == " "
    assert metadata["base_chunk_id"] == "c1"
    assert metadata["is_doc"] == "0"


def test_create_qa_pairs_ingests_each_pair_and_increments_task(rag):
    rag.ingest.return_value = None
    task = SimpleNamespace(completed_count=0, save=MagicMock())
    count = ChunkHelper.create_qa_pairs(
        [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": "a2"}],
        {"chunk_id": "base"},
        "idx",
        {"base_url": "http://e", "api_key": "k", "model": "m"},
        qa_pairs_id=3,
        task_obj=task,
    )
    assert count == 2
    assert task.completed_count == 2
    assert task.save.call_count == 2
    ingested = rag.ingest.call_args_list[0].args[0]
    assert ingested.docs[0].page_content == "q1"
    assert ingested.docs[0].metadata["qa_answer"] == "a1"


def test_create_qa_pairs_skips_failed_ingest(rag):
    rag.ingest.side_effect = [RuntimeError("boom"), None]
    task = SimpleNamespace(completed_count=0, save=MagicMock())
    count = ChunkHelper.create_qa_pairs(
        [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": "a2"}],
        {},
        "idx",
        {"model": "m"},
        qa_pairs_id=1,
        task_obj=task,
    )
    assert count == 1
    assert task.completed_count == 1


def test_create_one_qa_pairs_returns_result_flag(rag):
    rag.ingest.return_value = None
    assert ChunkHelper.create_one_qa_pairs({"model": "m"}, "idx", 1, "q", "a") == {"result": True}
    rag.ingest.side_effect = RuntimeError("x")
    assert ChunkHelper.create_one_qa_pairs({"model": "m"}, "idx", 1, "q", "a") == {"result": False}


def test_update_qa_pairs_success_and_failure(rag):
    rag.update_metadata.return_value = None
    assert ChunkHelper.update_qa_pairs("c1", "q", "a") == {"status": "success"}
    req = rag.update_metadata.call_args.args[0]
    assert req.chunk_ids == ["c1"]
    assert req.metadata == {"qa_question": "q", "qa_answer": "a"}
    rag.update_metadata.side_effect = RuntimeError("bad")
    failed = ChunkHelper.update_qa_pairs("c1", "q", "a")
    assert failed["status"] == "fail"
    assert "bad" in failed["message"]


def test_get_qa_content_requires_success_and_skips_empty_metadata(rag):
    rag.list_index_document.return_value = [
        Document(page_content="keep", metadata={"chunk_id": "c1", "knowledge_id": "k1"}),
        Document(page_content="drop", metadata={}),
    ]
    data = ChunkHelper.get_qa_content("k1", "idx")
    assert data == [{"chunk_id": "c1", "content": "keep", "knowledge_id": "k1"}]


def test_generate_question_and_answer_delegate_to_qa_generation(monkeypatch):
    monkeypatch.setattr(
        "apps.opspilot.utils.chunk_helper.QAGeneration.generate_question",
        lambda request: [{"question": "q?"}],
    )
    monkeypatch.setattr(
        "apps.opspilot.utils.chunk_helper.QAGeneration.generate_answer",
        lambda request: {"answer": "a!"},
    )
    q = ChunkHelper.generate_question({"content": "doc"})
    assert q == {"result": True, "data": [{"question": "q?"}]}
    a = ChunkHelper.generate_answer({"context": "doc", "content": "q?"})
    assert a["result"] is True
    assert a["data"]["answer"] == "a!"
    assert a["data"]["question"] == "q?"


def test_generate_qa_writes_pairs_and_counts_success(monkeypatch):
    monkeypatch.setattr(
        ChunkHelper,
        "generate_question",
        classmethod(lambda cls, kwargs: {"result": True, "data": [{"question": "q1"}, {"question": "q2"}]}),
    )
    monkeypatch.setattr(
        ChunkHelper,
        "generate_answer",
        classmethod(lambda cls, kwargs: {"result": True, "data": {"answer": "ans"}}),
    )
    created = []
    monkeypatch.setattr(
        ChunkHelper,
        "create_one_qa_pairs",
        classmethod(lambda cls, *args: created.append(args) or {"result": True}),
    )
    task = SimpleNamespace(completed_count=0, save=MagicMock())
    qa_pairs = SimpleNamespace(id=11)
    n = ChunkHelper.generate_qa(
        {},
        {},
        {"content": "chunk", "chunk_id": "c1"},
        {"model": "m"},
        "idx",
        qa_pairs,
        only_question=False,
        task_obj=task,
    )
    assert n == 2
    assert task.completed_count == 2
    assert created[0][2] == 11
    assert created[0][3] == "q1"
    assert created[0][4] == "ans"


def test_generate_qa_returns_zero_when_question_generation_fails(monkeypatch):
    monkeypatch.setattr(ChunkHelper, "generate_question", classmethod(lambda cls, kwargs: {"result": False, "data": []}))
    task = SimpleNamespace(completed_count=0, save=MagicMock())
    n = ChunkHelper.generate_qa({}, {}, {"content": "x", "chunk_id": "c"}, {}, "idx", SimpleNamespace(id=1), False, task)
    assert n == 0
    task.save.assert_not_called()
