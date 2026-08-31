"""Pgvector QueryBuilder：元数据过滤与排序字段白名单（防 SQL 注入）。"""
from types import SimpleNamespace

import pytest

from apps.opspilot.metis.llm.rag.naive_rag.pgvector.query_builder import QueryBuilder

pytestmark = pytest.mark.unit


def test_build_metadata_filter_empty_returns_blank():
    params = {}
    assert QueryBuilder.build_metadata_filter({}, params) == ""
    assert params == {}


def test_build_metadata_filter_combines_operators():
    params = {}
    clause = QueryBuilder.build_metadata_filter(
        {
            "knowledge_id": "kb-1",
            "tag__exists": True,
            "gone__missing": True,
            "title__like": "%告警%",
            "name__ilike": "%node%",
            "note__not_blank": True,
            "segment_id__in": ["s1", "s2"],
            "empty__in": [],
        },
        params,
    )
    assert clause.startswith("(") and clause.endswith(")")
    assert "e.cmetadata ? %(metadata_tag_exists)s" in clause
    assert "NOT (e.cmetadata ? %(metadata_gone_missing)s)" in clause
    assert "LIKE" in clause and "ILIKE" in clause
    assert "TRIM(" in clause
    assert "ANY(%(metadata_segment_id__in_value)s)" in clause
    assert "empty__in" not in clause
    assert params["metadata_knowledge_id_value"] == "kb-1"
    assert params["metadata_segment_id__in_value"] == ["s1", "s2"]


def test_build_document_list_query_uses_whitelist_sort_and_pagination():
    params = {}
    req = SimpleNamespace(sort_order="ASC; DROP TABLE x", sort_field="created_time;drop", page=2, size=10)
    sql = QueryBuilder.build_document_list_query(req, "c.name = %(index_name)s", params)
    assert "DROP TABLE" not in sql
    assert params["sort_field"] == "created_time"
    assert "ORDER BY (e.cmetadata->>%(sort_field)s)::timestamp DESC" in sql
    assert params["limit"] == 10
    assert params["offset"] == 10

    params2 = {}
    req2 = SimpleNamespace(sort_order="asc", sort_field="knowledge_id", page=0, size=0)
    sql2 = QueryBuilder.build_document_list_query(req2, "TRUE", params2)
    assert "timestamp ASC" in sql2
    assert "LIMIT" not in sql2
