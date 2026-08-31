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
    DocumentIngestRequest,
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


def test_process_documents_pipeline_preview_does_not_store(rag, monkeypatch):
    stored = []
    monkeypatch.setattr(rag, "store_documents_to_pg", lambda **kwargs: stored.append(kwargs))
    docs = [Document(page_content="hello world " * 20, metadata={})]
    params = {
        "is_preview": True,
        "chunk_mode": "full",
        "knowledge_id": "k1",
        "knowledge_base_id": "kb",
        "embed_model_base_url": "",
        "embed_model_api_key": "",
        "embed_model_name": "m",
        "metadata": {},
    }
    result = rag._process_documents_pipeline(docs, "title", params, "自定义内容")
    assert result["status"] == "success"
    assert result["chunks_size"] >= 1
    assert result["documents"][0]["page_content"]
    assert stored == []

    params["is_preview"] = False
    persist = rag._process_documents_pipeline(docs, "title", params, "自定义内容")
    assert persist["status"] == "success"
    assert persist["chunks_size"] >= 1
    assert stored and stored[0]["knowledge_base_id"] == "kb"


def test_search_by_type_sets_is_doc_and_swallows_errors(rag, monkeypatch):
    captured = {}

    def fake_perform(req):
        captured["filter"] = dict(req.metadata_filter)
        captured["k"] = req.k
        return [Document(page_content="hit", metadata={"embedding": [1]})]

    monkeypatch.setattr(rag, "_perform_search", fake_perform)
    req = DocumentRetrieverRequest(index_name="kb", qa_size=3, enable_rerank=False, rag_recall_mode="chunk")
    naive = rag._search_by_type(req, "naive")
    assert captured["filter"]["is_doc"] == "1"
    assert naive[0].page_content == "hit"
    qa = rag._search_by_type(req, "qa")
    assert captured["filter"]["is_doc"] == "0"
    assert captured["k"] == 3
    monkeypatch.setattr(rag, "_perform_search", lambda req: (_ for _ in ()).throw(RuntimeError("down")))
    assert rag._search_by_type(req, "naive") == []


def test_similarity_and_mmr_search_attach_scores(rag):
    scored = Document(page_content="alpha-doc extra", metadata={})
    store = MagicMock()
    store.similarity_search_with_relevance_scores.return_value = [(scored, 0.88)]
    store.max_marginal_relevance_search.return_value = [scored]
    req = DocumentRetrieverRequest(index_name="kb", search_query="q", k=2, search_type="similarity_score_threshold")
    sim = rag._execute_similarity_search(store, req, {"k": 2, "filter": {"is_doc": {"$eq": "1"}}})
    assert sim[0].metadata["search_method"] == "similarity"
    assert sim[0].metadata["similarity_score"] == pytest.approx(0.88)
    mmr_req = DocumentRetrieverRequest(index_name="kb", search_query="q", k=1, search_type="mmr")
    mmr = rag._execute_mmr_search(store, mmr_req, {"k": 1})
    assert mmr[0].metadata["search_method"] == "mmr"
    assert mmr[0].metadata["similarity_score"] == pytest.approx(0.88)


def test_list_index_document_maps_rows_and_missing_index(rag):
    rag._db_manager.execute_query.return_value = [{"id": "c1", "document": "body", "cmetadata": {"k": "v"}, "qa_count": 1}]
    docs = rag.list_index_document(DocumentListRequest(index_name="kb", page=1, size=10, query="body", metadata_filter={}))
    assert docs[0].metadata["chunk_id"] == "c1"
    rag._db_manager.execute_query.side_effect = RuntimeError('relation "langchain_pg_embedding" does not exist')
    assert rag.list_index_document(DocumentListRequest(index_name="kb", page=1, size=10, query="", metadata_filter={})) == []
    rag._db_manager.execute_query.side_effect = RuntimeError("permission denied")
    with pytest.raises(RuntimeError, match="permission denied"):
        rag.list_index_document(DocumentListRequest(index_name="kb", page=1, size=10, query="", metadata_filter={}))


def test_custom_content_ingest_preview_and_store(rag, monkeypatch):
    stored = []
    monkeypatch.setattr(rag, "store_documents_to_pg", lambda **kwargs: stored.append(kwargs))
    params = {
        "is_preview": True,
        "chunk_mode": "full",
        "knowledge_id": "k1",
        "knowledge_base_id": "kb",
        "embed_model_base_url": "",
        "embed_model_api_key": "",
        "embed_model_name": "m",
        "metadata": {"source": "manual"},
    }
    preview = rag.custom_content_ingest("hello", params)
    assert preview["status"] == "success"
    assert stored == []
    params["is_preview"] = False
    persisted = rag.custom_content_ingest("hello", params)
    assert persisted["status"] == "success"
    assert persisted["chunks_size"] >= 1
    assert stored and stored[0]["metadata"]["source"] == "manual"


def test_file_ingest_rejects_unknown_type(rag):
    out = rag.file_ingest("/tmp/a.bin", "a.bin", {"is_preview": True})
    assert out["status"] == "error"
    assert "不支持的文件类型" in out["message"]


def test_perform_search_routes_mmr_and_swallows_errors(rag, monkeypatch):
    req = DocumentRetrieverRequest(index_name="kb", search_query="q", search_type="mmr")
    monkeypatch.setattr(rag, "_create_vector_store", lambda req: "store")
    monkeypatch.setattr(rag, "_execute_mmr_search", lambda store, req, kwargs: [Document(page_content="mmr")])
    monkeypatch.setattr(rag, "_execute_similarity_search", lambda store, req, kwargs: [Document(page_content="sim")])
    assert rag._perform_search(req)[0].page_content == "mmr"
    sim_req = DocumentRetrieverRequest(index_name="kb", search_query="q", search_type="similarity_score_threshold")
    assert rag._perform_search(sim_req)[0].page_content == "sim"
    monkeypatch.setattr(rag, "_create_vector_store", lambda req: (_ for _ in ()).throw(RuntimeError("bad")))
    assert rag._perform_search(req) == []


def test_create_vector_store_and_rerank_and_ingest(rag, monkeypatch):
    embed = object()

    class FakeEM:
        def get_embed(self, *a, **k):
            return embed

    monkeypatch.setattr("apps.opspilot.metis.llm.rag.naive_rag.pgvector.pgvector_rag.EmbedManager", FakeEM)
    added = []

    class FakePG:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def add_documents(self, docs, ids):
            added.append((docs, ids))

    monkeypatch.setattr("apps.opspilot.metis.llm.rag.naive_rag.pgvector.pgvector_rag.PGVector", FakePG)
    req = DocumentRetrieverRequest(index_name="kb-store", embed_model_name="m")
    store = rag._create_vector_store(req)
    assert store.kwargs["collection_name"] == "kb-store"
    assert store.kwargs["embeddings"] is embed
    assert store.kwargs["use_jsonb"] is True

    docs = [Document(page_content="q", metadata={"chunk_id": "c1"})]
    monkeypatch.setattr(
        "apps.opspilot.metis.llm.rag.naive_rag.pgvector.pgvector_rag.ReRankManager.rerank_documents",
        lambda **kwargs: [Document(page_content="ranked")],
    )
    rerank_req = DocumentRetrieverRequest(index_name="kb", search_query="q", enable_rerank=True)
    assert rag._rerank_results(rerank_req, []) == []
    ranked = rag._rerank_results(rerank_req, docs)
    assert ranked[0].page_content == "ranked"

    rag._db_manager.execute_update.return_value = 2
    ids = rag.ingest(DocumentIngestRequest(index_name="kb-in", index_mode="overwrite", docs=docs))
    assert ids == ["c1"]
    rag._db_manager.execute_update.assert_called_once()
    assert added[-1][1] == ["c1"]
    added.clear()
    ids = rag.ingest(DocumentIngestRequest(index_name="kb-in", docs=docs))
    assert ids == ["c1"]
    rag._db_manager.execute_update.assert_called_once()
    monkeypatch.setattr(FakePG, "add_documents", lambda self, docs, ids: (_ for _ in ()).throw(RuntimeError("embed-fail")))
    with pytest.raises(RuntimeError, match="embed-fail"):
        rag.ingest(DocumentIngestRequest(index_name="kb-in", docs=docs))


def test_store_documents_to_pg_and_website_file_ingest(rag, monkeypatch):
    ingested = []
    monkeypatch.setattr(PgvectorRag, "ingest", lambda self, req: ingested.append(req) or ["c1"])
    docs = [Document(page_content="body", metadata={})]
    PgvectorRag.store_documents_to_pg(docs, "kb-1", "", "", "embed", metadata={"src": "web"})
    assert ingested[0].index_name == "kb-1"
    assert docs[0].metadata["src"] == "web"
    assert docs[0].metadata["created_time"]

    chunked = PgvectorRag.perform_chunking([Document(page_content="hello world", metadata={})], "full", {}, True, "文本")
    assert chunked[0].page_content

    monkeypatch.setattr(
        "apps.opspilot.metis.llm.rag.naive_rag.pgvector.pgvector_rag.OcrManager.load_ocr",
        lambda **kwargs: "ocr",
    )
    loader = MagicMock()
    loader.load.return_value = [Document(page_content="site", metadata={})]
    monkeypatch.setattr("apps.opspilot.metis.llm.rag.naive_rag.pgvector.pgvector_rag.WebSiteLoader", lambda *a, **k: loader)
    monkeypatch.setattr(rag, "_process_documents_pipeline", lambda docs, title, params, content_type: {"status": "success", "chunks_size": 1, "title": title})
    web = rag.website_ingest("https://example.com", 1, {"is_preview": True})
    assert web == {"status": "success", "chunks_size": 1, "title": "https://example.com"}

    file_loader = MagicMock()
    file_loader.load.return_value = [Document(page_content="file", metadata={})]
    monkeypatch.setattr(rag, "get_file_loader", lambda *a, **k: file_loader)
    file_out = rag.file_ingest("/tmp/a.md", "a.md", {"is_preview": True, "load_mode": "full"})
    assert file_out["status"] == "success"
    assert file_out["chunks_size"] == 1
    monkeypatch.setattr(rag, "get_file_loader", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("load-fail")))
    with pytest.raises(RuntimeError, match="load-fail"):
        rag.file_ingest("/tmp/a.md", "a.md", {"is_preview": True})
