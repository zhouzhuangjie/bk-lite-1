"""FalkorDB 连接关闭、表格字段编解码失败与拓扑查询编排。"""
from unittest.mock import MagicMock

import pytest

from apps.cmdb.graph.falkordb import FalkorDBClient, FalkorDBConnectionPool
from apps.cmdb.tests.test_falkordb_client import FakeResultSet, _client

pytestmark = pytest.mark.unit


def test_connection_pool_close_invalidates_even_if_client_close_raises():
    class BrokenClient:
        def close(self):
            raise RuntimeError("already closed")

    pool = FalkorDBConnectionPool()
    original_initialized = pool._initialized
    original_client = pool._client
    original_graph = pool._graph
    pool._client = BrokenClient()
    pool._graph = object()
    pool._initialized = True
    try:
        pool.close()
        assert pool._initialized is False
        assert pool._client is None
        assert pool._graph is None
    finally:
        pool._initialized = original_initialized
        pool._client = original_client
        pool._graph = original_graph


def test_serialize_table_fields_skips_non_instance_and_keeps_unserializable_list():
    client = FalkorDBClient()
    raw = {"tbl": [{"a": 1}]}
    assert client._serialize_table_fields("model", raw, [{"attr_id": "tbl", "attr_type": "table"}]) is raw
    no_table = client._serialize_table_fields("instance", {"name": "h"}, [{"attr_id": "cpu", "attr_type": "str"}])
    assert no_table == {"name": "h"}

    props = {"tbl": [object()]}
    out = client._serialize_table_fields("instance", props, [{"attr_id": "tbl", "attr_type": "table"}])
    assert out["tbl"] is props["tbl"]


def test_deserialize_table_fields_invalid_json_becomes_empty_list():
    client = FalkorDBClient()
    attrs = [{"attr_id": "tbl", "attr_type": "table"}]
    assert client._deserialize_table_fields_in_result_list([], attrs) == []
    rows = [{"tbl": "[1, 2]", "name": "h"}, {"tbl": "not-json"}]
    out = client._deserialize_table_fields_in_result_list(rows, attrs)
    assert out[0]["tbl"] == [1, 2]
    assert out[1]["tbl"] == []


def test_query_topo_test_config_returns_src_and_dst_format_topo():
    client = _client(FakeResultSet([], []))
    client.convert_to_cypher_match = lambda *args, **kwargs: "MATCH p=()"
    client.format_topo = lambda inst_id, objs, flag: {"inst": inst_id, "src_side": flag}
    out = client.query_topo_test_config("instance", 42, "host")
    assert out["src_result"] == {"inst": 42, "src_side": True}
    assert out["dst_result"] == {"inst": 42, "src_side": False}


def test_get_topo_config_returns_empty_when_file_missing(monkeypatch):
    monkeypatch.setattr("os.path.isfile", lambda path: False)
    assert FalkorDBClient.get_topo_config() == {}
