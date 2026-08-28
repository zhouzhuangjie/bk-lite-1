"""Neo4j 客户端剩余路径：批量创建、计数、网络拓扑、全文检索。"""
from unittest.mock import patch

import pytest

from apps.cmdb.graph.neo4j import Neo4jClient
from apps.cmdb.tests.test_neo4j_client import FakeNode, FakeRel, FakeRunResult, FakeSession, _client
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.unit


class DictRecord(dict):
    def __getitem__(self, item):
        return dict.__getitem__(self, item)


def test_batch_create_entity_and_edge_collect_failures():
    created = FakeNode(9, ["instance"], {"inst_name": "ok"})
    c = _client([(created,)])
    with patch.object(c, "_create_entity", side_effect=[{"_id": 1}, BaseAppException("dup")]):
        rows = c.batch_create_entity(
            "instance",
            [{"inst_name": "a"}, {"inst_name": "b"}],
            {"is_only": {}, "is_required": {}},
            [],
            operator="admin",
        )
    assert rows[0]["success"] is True
    assert rows[1]["success"] is False
    assert "article 2" in rows[1]["message"]

    with patch.object(c, "_create_edge", side_effect=[{"_id": 3}, RuntimeError("cycle")]):
        edges = c.batch_create_edge(
            "connects",
            "instance",
            "instance",
            [{"src_id": 1, "dst_id": 2}, {"src_id": 2, "dst_id": 3}],
            "connect",
        )
    assert edges[0]["success"] is True
    assert edges[1]["success"] is False


def test_entity_count_groups_and_applies_permission():
    records = [DictRecord({"model_id": "host", "count": 3}), DictRecord({"model_id": "switch", "count": 1})]
    c = _client(records)
    out = c.entity_count(
        "instance",
        "model_id",
        params=[{"field": "organization", "type": "list[]", "value": [1]}],
        permission_params="n.org=1",
        instance_permission_params=[{"model_id": "host", "inst_names": ["h1"]}],
        created="alice",
    )
    assert out == {"host": 3, "switch": 1}
    assert "COUNT(n)" in c.session.last_query
    assert "n.model_id" in c.session.last_query


def test_query_network_topo_maps_records():
    record = DictRecord(
        {
            "dev_id": 1,
            "dev_name": "sw1",
            "dev_model": "switch",
            "local_if": "eth0",
            "peer_if": "eth1",
            "peer_id": 2,
            "peer_name": "sw2",
            "peer_model": "switch",
            "rel_id": 9,
        }
    )
    c = _client([record])
    rows = c.query_network_topo(1, "interface_belong_switch")
    assert rows[0]["peer_name"] == "sw2"
    assert rows[0]["local_if"] == "eth0"
    assert "MATCH (i)-[e1]->(dev)" in c.session.last_query


def test_full_text_builds_permission_where():
    node = FakeNode(1, ["instance"], {"inst_name": "h1"})
    c = _client([(node,)])
    rows = c.full_text("h1", permission_params="n.org=1", instance_permission_params=[{"model_id": "host", "inst_names": ["h1"]}], created="alice")
    assert rows[0]["_id"] == 1
    assert "CONTAINS" in c.session.last_query.upper() or "h1" in c.session.last_query


def test_query_entity_by_ids_empty_returns_empty_list():
    c = _client([])
    assert c.query_entity_by_ids([]) == []


def test_format_topo_empty_peek_returns_empty():
    class EmptyResult(FakeRunResult):
        def peek(self):
            return None

    class PeekSession(FakeSession):
        def run(self, query, *args, **kwargs):
            self.last_query = query
            return EmptyResult([])

    c = _client()
    c.session = PeekSession([])
    assert c.format_topo(1, c.session.run("MATCH (n) RETURN n"), True) == {}
    assert c.format_topo_lite(1, c.session.run("MATCH (n) RETURN n"), True) == {}


def test_close_and_context_manager_close_session(monkeypatch):
    class DummyDriver:
        def __init__(self):
            self.closed = False
            self.session_obj = FakeSession([])

        def session(self):
            return self.session_obj

        def close(self):
            self.closed = True

    driver = DummyDriver()
    monkeypatch.setattr("apps.cmdb.graph.neo4j.GraphDatabase.driver", lambda *a, **k: driver)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "pass")
    with Neo4jClient() as client:
        assert client.session is driver.session_obj
    assert driver.closed is True
