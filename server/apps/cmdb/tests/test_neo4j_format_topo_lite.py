"""Neo4jClient.format_topo_lite / create_node_lite：空结果、排除节点、深度裁剪。"""
import pytest

from apps.cmdb.graph.neo4j import Neo4jClient

pytestmark = pytest.mark.unit


class _FakePath:
    def __init__(self, nodes, relationships):
        self.nodes = nodes
        self.relationships = relationships


class _FakeNode:
    def __init__(self, nid, label, properties):
        self.id = nid
        self.labels = [label]
        self._properties = properties


class _FakeRel:
    def __init__(self, rid, rtype, properties):
        self.id = rid
        self.type = rtype
        self._properties = properties


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def peek(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


def _client():
    return Neo4jClient.__new__(Neo4jClient)


def test_format_topo_lite_empty_when_no_rows(monkeypatch):
    monkeypatch.setattr("apps.cmdb.graph.neo4j.Path", _FakePath)
    client = _client()
    assert client.format_topo_lite(1, _FakeResult([])) == {}


def test_format_topo_lite_builds_tree_and_excludes_nodes(monkeypatch):
    monkeypatch.setattr("apps.cmdb.graph.neo4j.Path", _FakePath)
    n1 = _FakeNode(1, "instance", {"model_id": "host", "inst_name": "a"})
    n2 = _FakeNode(2, "instance", {"model_id": "host", "inst_name": "b"})
    n3 = _FakeNode(3, "instance", {"model_id": "host", "inst_name": "c"})
    r12 = _FakeRel(10, "link", {"src_inst_id": 1, "dst_inst_id": 2, "model_asst_id": "host-host", "asst_id": "connect"})
    r23 = _FakeRel(11, "link", {"src_inst_id": 2, "dst_inst_id": 3, "model_asst_id": "host-host", "asst_id": "connect"})
    path = _FakePath([n1, n2, n3], [r12, r23])
    client = _client()
    tree = client.format_topo_lite(1, _FakeResult([[path]]), depth=3)
    assert tree["_id"] == 1
    assert tree["inst_name"] == "a"
    assert tree["children"][0]["_id"] == 2
    assert tree["children"][0]["children"][0]["_id"] == 3

    excluded = client.format_topo_lite(1, _FakeResult([[path]]), depth=3, exclude_ids=["2", "bad"])
    assert excluded["_id"] == 1
    assert excluded["children"] == []


def test_create_node_lite_has_more_at_max_depth():
    client = _client()
    entity = {"_id": 1, "model_id": "host", "inst_name": "root"}
    edges = [{"src_inst_id": 1, "dst_inst_id": 2}]
    node = client.create_node_lite(entity, edges, [entity], entity_is_src=True, level=3, max_depth=3)
    assert node["has_more"] is True
    assert node["children"] == []
