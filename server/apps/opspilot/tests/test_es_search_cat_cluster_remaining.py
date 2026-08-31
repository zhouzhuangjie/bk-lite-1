"""Elasticsearch search/cat/cluster/documents/mappings：成功与 es_error 信封。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.metis.llm.tools.elasticsearch import cat, cluster, documents, mappings, search

pytestmark = pytest.mark.unit


def test_search_success_and_error():
    client = MagicMock()
    client.search.return_value = {"took": 3, "timed_out": False, "hits": {"total": {"value": 2}, "hits": [{"_id": "1"}]}}
    client.count.return_value = {"count": 2}
    with patch.object(search, "get_es_client", return_value=client):
        out = search.es_search.invoke({"index": "logs", "query": {"match_all": {}}})
        counted = search.es_count.invoke({"index": "logs"})
    assert out == {"success": True, "data": {"took": 3, "timed_out": False, "total": 2, "hits": [{"_id": "1"}], "aggregations": None}, "index": "logs"}
    assert counted["data"]["count"] == 2
    with patch.object(search, "get_es_client", side_effect=RuntimeError("down")):
        err = search.es_search.invoke({"index": "logs", "query": {}})
        knn = search.es_knn_search.invoke({"index": "logs", "knn": {"field": "v"}})
        explained = search.es_explain.invoke({"index": "logs", "doc_id": "1", "query": {}})
        templated = search.es_search_template.invoke({"index": "logs", "source": {}})
        msearch = search.es_multi_search.invoke({"searches": []})
        validated = search.es_validate_query.invoke({"index": "logs", "query": {}})
    for item in (err, knn, explained, templated, msearch, validated):
        assert item == {"success": False, "error": "down", "error_type": "es_error"}


def test_cat_cluster_mappings_documents_success_and_error():
    client = MagicMock()
    client.cat.indices.return_value = [{"index": "logs"}]
    client.cluster.health.return_value = {"status": "green"}
    client.indices.get_mapping.return_value = {"logs": {}}
    client.get.return_value = {"_id": "1"}
    client.ping.return_value = True
    with patch.object(cat, "get_es_client", return_value=client):
        assert cat.es_cat_indices.invoke({"index": "logs"})["success"] is True
        assert cat.es_cat_shards.invoke({})["success"] is True
        assert cat.es_cat_nodes.invoke({})["success"] is True
        assert cat.es_cat_aliases.invoke({})["success"] is True
        assert cat.es_cat_allocation.invoke({})["success"] is True
        assert cat.es_cat_recovery.invoke({})["success"] is True
    with patch.object(cluster, "get_es_client", return_value=client):
        ping = cluster.es_ping.invoke({})
        health = cluster.es_cluster_health.invoke({"index": "logs"})
        assert ping["data"]["pong"] is True
        assert health["data"]["status"] == "green"
        assert cluster.es_info.invoke({})["success"] is True
        assert cluster.es_cluster_stats.invoke({})["success"] is True
        assert cluster.es_nodes_info.invoke({})["success"] is True
        assert cluster.es_nodes_stats.invoke({})["success"] is True
    with patch.object(mappings, "get_es_client", return_value=client):
        assert mappings.es_get_mapping.invoke({"index": "logs"})["success"] is True
        assert mappings.es_get_settings.invoke({"index": "logs"})["success"] is True
        assert mappings.es_put_mapping.invoke({"index": "logs", "body": {}})["success"] is True
        assert mappings.es_put_settings.invoke({"index": "logs", "body": {}})["success"] is True
        assert mappings.es_field_caps.invoke({"index": "logs", "fields": ["a"]})["success"] is True
    with patch.object(documents, "get_es_client", return_value=client):
        got = documents.es_get_document.invoke({"index": "logs", "doc_id": "1"})
        assert got["doc_id"] == "1"
        assert documents.es_index_document.invoke({"index": "logs", "document": {"a": 1}})["success"] is True
        assert documents.es_update_document.invoke({"index": "logs", "doc_id": "1", "doc": {"a": 2}})["success"] is True
        assert documents.es_multi_get.invoke({"index": "logs", "ids": ["1"]})["success"] is True
        deleted = documents.es_delete_document.invoke({"index": "logs", "doc_id": "1", "confirm": True})
        bulk = documents.es_bulk.invoke({"operations": [], "confirm": True})
        assert deleted["success"] is True and bulk["success"] is True
    denied = documents.es_delete_document.invoke({"index": "logs", "doc_id": "1", "confirm": False})
    assert denied["error_type"] == "confirmation_required"
    with patch.object(cat, "get_es_client", side_effect=RuntimeError("down")):
        assert cat.es_cat_nodes.invoke({}) == {"success": False, "error": "down", "error_type": "es_error"}
    with patch.object(cluster, "get_es_client", side_effect=RuntimeError("down")):
        ping_err = cluster.es_ping.invoke({})
        assert ping_err == {"success": False, "error": "down", "error_type": "connection_error"}
    with patch.object(documents, "get_es_client", side_effect=RuntimeError("missing")):
        not_found = documents.es_get_document.invoke({"index": "logs", "doc_id": "1"})
    assert not_found == {"success": False, "error": "missing", "error_type": "not_found"}
    with patch.object(mappings, "get_es_client", side_effect=RuntimeError("down")):
        mapped = mappings.es_get_mapping.invoke({"index": "logs"})
    assert mapped == {"success": False, "error": "down", "error_type": "es_error"}
