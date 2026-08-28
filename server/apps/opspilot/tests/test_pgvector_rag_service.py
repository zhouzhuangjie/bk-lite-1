"""PgvectorRag 可测行为：过滤器、MMR 分数、分块器选择、CRUD 跳过空目标。"""
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from apps.opspilot.metis.llm.chunk.fixed_size_chunk import FixedSizeChunk
from apps.opspilot.metis.llm.chunk.full_chunk import FullChunk
from apps.opspilot.metis.llm.chunk.recursive_chunk import RecursiveChunk
from apps.opspilot.metis.llm.rag.naive_rag.pgvector.pgvector_rag import PgvectorRag
from apps.opspilot.metis.llm.rag.naive_rag_entity import (
    DocumentCountRequest,
    DocumentDeleteRequest,
    DocumentListRequest,
    DocumentMetadataUpdateRequest,
    DocumentRetrieverRequest,
    IndexDeleteRequest,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def rag(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(
        "apps.opspilot.metis.llm.rag.naive_rag.pgvector.pgvector_rag.DatabaseManager",
        lambda url: db,
    )
    monkeypatch.setenv("METIS_DB_URI", "postgresql://unused")
    instance = PgvectorRag()
    instance._db_manager = db
    return instance


def test_build_pgvector_filter_maps_operators(rag):
    assert rag._build_pgvector_filter({}) == {}
    mapped = rag._build_pgvector_filter(
        {
            "tag__exists": True,
            "gone__missing": True,
            "title__like": "%a%",
            "name__ilike": "%b%",
            "note__not_blank": True,
            "ids__in": ["1", "2"],
            "empty__in": [],
            "knowledge_id": "kb",
        }
    )
    assert mapped["tag"] == {"$ne": None}
    assert mapped["gone"] == {"$eq": None}
    assert mapped["title"] == {"$like": "%a%"}
    assert mapped["name"] == {"$ilike": "%b%"}
    assert mapped["note"] == {"$ne": ""}
    assert mapped["ids"] == {"$in": ["1", "2"]}
    assert "empty" not in mapped
    assert mapped["knowledge_id"] == {"$eq": "kb"}


def test_set_mmr_scores_uses_map_then_rank_fallback(rag):
    scored = Document(page_content="alpha-doc extra")
    missing = Document(page_content="beta-doc")
    rag._set_mmr_scores([scored, missing], [(Document(page_content="alpha-doc extra"), 0.91)])
    assert scored.metadata["similarity_score"] == 0.91
    assert scored.metadata["search_method"] == "mmr"
    assert missing.metadata["mmr_rank"] == 2
    assert missing.metadata["similarity_score"] == pytest.approx(0.9)


def test_add_search_metadata_and_collect_chunk_ids(rag):
    docs = [Document(page_content="x", metadata={})]
    req = DocumentRetrieverRequest(index_name="kb", search_type="mmr")
    rag._add_search_metadata(docs, req)
    assert docs[0].metadata["index_name"] == "kb"
    assert docs[0].metadata["rank"] == 1

    rag._db_manager.execute_query.return_value = [{"id": "c2"}, {"id": "c3"}]
    ids = rag._collect_target_chunk_ids(["c1", "c2"], ["kb-1"])
    assert set(ids) == {"c1", "c2", "c3"}
    assert rag._get_chunk_ids_by_knowledge_ids([]) == []


def test_build_where_clauses_adds_index_metadata_and_query(rag):
    req = DocumentListRequest(index_name="kb", page=1, size=10, metadata_filter={"k": "v"}, query="alert")
    where, params = [], {}
    rag._build_where_clauses(req, where, params)
    assert where[0] == "c.name = %(index_name)s"
    assert params["index_name"] == "kb"
    assert params["query_pattern"] == "%alert%"
    assert any("cmetadata" in clause for clause in where)


def test_count_and_delete_index_tolerate_missing_relation(rag):
    rag._db_manager.execute_query.side_effect = RuntimeError('relation "langchain_pg_embedding" does not exist')
    count = rag.count_index_document(DocumentCountRequest(index_name="kb", query=""))
    assert count == 0

    rag._db_manager.execute_update.side_effect = RuntimeError("does not exist")
    rag.delete_index(IndexDeleteRequest(index_name="kb"))


def test_update_metadata_skips_when_no_chunks(rag):
    rag.update_metadata(DocumentMetadataUpdateRequest())
    rag._db_manager.execute_update.assert_not_called()

    rag._db_manager.execute_query.side_effect = [[{"id": "c1"}], [{"id": "c1"}]]
    rag._db_manager.execute_update.return_value = 1
    rag.update_metadata(DocumentMetadataUpdateRequest(chunk_ids=["c1"], metadata={"k": "v"}))
    rag._db_manager.execute_update.assert_called_once()


def test_serialize_process_documents_and_chunkers(rag, monkeypatch):
    docs = [Document(page_content="hello", metadata={})]
    rag.process_documents(docs, "title", knowledge_id="kid")
    assert docs[0].metadata["knowledge_title"] == "title"
    assert docs[0].metadata["knowledge_id"] == "kid"
    assert docs[0].metadata["segment_number"] == "0"
    serialized = rag.serialize_documents(docs)
    assert serialized[0]["page_content"] == "hello"

    preview = rag.prepare_documents_metadata([Document(page_content="p", metadata={})], True, "t")
    assert "knowledge_id" not in preview[0].metadata

    assert isinstance(rag.get_chunker("fixed_size", {"chunk_size": "128"}), FixedSizeChunk)
    assert isinstance(rag.get_chunker("full", {}), FullChunk)
    chunker = rag.get_chunker("recursive", {"chunk_size": "64", "chunk_overlap": "8"})
    assert isinstance(chunker, RecursiveChunk)
    with pytest.raises(ValueError, match="不支持的分块模式"):
        rag.get_chunker("unknown", {})


def test_get_file_loader_routes_by_extension(rag, monkeypatch):
    monkeypatch.setattr(
        "apps.opspilot.metis.llm.rag.naive_rag.pgvector.pgvector_rag.OcrManager.load_ocr",
        lambda **kwargs: "ocr",
    )
    assert rag.get_file_loader("/a.txt", "txt", "full", {}).__class__.__name__ == "TextLoader"
    assert rag.get_file_loader("/a.md", "md", "full", {}).__class__.__name__ == "MarkdownLoader"
    assert rag.get_file_loader("/a.csv", "csv", "full", {}).__class__.__name__ == "ExcelLoader"
    with pytest.raises(ValueError, match="不支持的文件类型"):
        rag.get_file_loader("/a.bin", "bin", "full", {})


def test_process_search_results_strips_vectors_and_appends_qa(rag, monkeypatch):
    doc = Document(page_content="q", metadata={"embedding": [1], "vector": [2], "qa_answer": "a"})
    req = DocumentRetrieverRequest(index_name="kb", enable_rerank=False, rag_recall_mode="chunk")
    results = rag._process_search_results([doc], req, "naive")
    assert "embedding" not in results[0].metadata
    assert results[0].page_content.endswith("\na")


def test_search_combines_naive_and_qa(rag, monkeypatch):
    monkeypatch.setattr(rag, "_search_by_type", lambda req, rag_type: [Document(page_content=rag_type, metadata={})])
    req = DocumentRetrieverRequest(index_name="kb", enable_naive_rag=True, enable_qa_rag=True)
    results = rag.search(req)
    assert [doc.page_content for doc in results] == ["naive", "qa"]


def test_delete_document_skips_empty_and_clears_qa(rag):
    rag.delete_document(DocumentDeleteRequest(chunk_ids=[], knowledge_ids=[], keep_qa=False))
    rag._db_manager.execute_update.assert_not_called()

    rag._db_manager.execute_update.return_value = 1
    rag.delete_document(DocumentDeleteRequest(chunk_ids=["c1"], knowledge_ids=[], keep_qa=False))
    sqls = [call.args[0] for call in rag._db_manager.execute_update.call_args_list]
    assert any("DELETE FROM langchain_pg_embedding" in sql and "base_chunk_id" in sql for sql in sqls)
    assert any("DELETE FROM langchain_pg_embedding WHERE id = ANY" in sql for sql in sqls)

    rag._db_manager.execute_update.reset_mock()
    rag.delete_document(DocumentDeleteRequest(chunk_ids=["c1"], knowledge_ids=[], keep_qa=True))
    keep_sql = rag._db_manager.execute_update.call_args_list[0].args[0]
    assert "jsonb_set" in keep_sql


def test_process_recall_stage_falls_back_to_chunk(rag, monkeypatch):
    docs = [Document(page_content="hit", metadata={})]
    req = DocumentRetrieverRequest(index_name="kb", rag_recall_mode="missing-mode")
    out = rag.process_recall_stage(req, docs)
    assert out == docs


def test_convert_results_to_documents_and_search_kwargs(rag):
    docs = rag._convert_results_to_documents(
        [{"id": "c1", "document": "body", "cmetadata": {"k": "v"}, "qa_count": 2}]
    )
    assert docs[0].page_content == "body"
    assert docs[0].metadata["chunk_id"] == "c1"
    assert docs[0].metadata["qa_count"] == 2
    req = DocumentRetrieverRequest(index_name="kb", metadata_filter={"k": "v"}, k=4)
    kwargs = rag._build_search_kwargs(req)
    assert kwargs["k"] == 4
    assert kwargs["filter"]["k"] == {"$eq": "v"}
