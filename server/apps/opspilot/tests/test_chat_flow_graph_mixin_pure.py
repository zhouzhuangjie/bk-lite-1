"""ChatFlow 图结构 mixin：入口识别、拓扑、BFS 找 agents/意图节点。"""
from graphlib import CycleError

import pytest

from apps.opspilot.utils.chat_flow_utils.engine.flow_graph import FlowGraphMixin

pytestmark = pytest.mark.unit


class _Graph(FlowGraphMixin):
    def __init__(self, nodes, edges, start=None):
        self.nodes = nodes
        self.edges = edges
        self._node_map = {n["id"]: n for n in nodes}
        self.start_node_id = start or (nodes[0]["id"] if nodes else None)


def test_parse_and_identify_entry_nodes():
    g = _Graph([], [])
    flow = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"source": "a", "target": "b"}]}
    assert [n["id"] for n in g._parse_nodes(flow)] == ["a", "b"]
    assert g._parse_edges(flow)[0]["target"] == "b"
    g = _Graph(flow["nodes"], flow["edges"])
    assert g._identify_entry_nodes() == ["a"]
    assert g._get_node_by_id("b")["id"] == "b"
    assert g._get_node_by_id("missing") is None


def test_build_topology_detects_cycle():
    g = _Graph(
        [{"id": "a"}, {"id": "b"}],
        [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
    )
    topo = g._build_topology()
    with pytest.raises(CycleError):
        list(topo.static_order())


def test_bfs_finds_agents_and_stops_at_intent():
    nodes = [
        {"id": "start", "type": "openai"},
        {"id": "mid", "type": "http"},
        {"id": "agent", "type": "agents"},
    ]
    edges = [{"source": "start", "target": "mid"}, {"source": "mid", "target": "agent"}]
    g = _Graph(nodes, edges, start="start")
    found, path = g._find_agent_node_via_bfs(nodes[0])
    assert found["id"] == "agent"
    assert any(n["id"] == "mid" for n in path)

    intent_nodes = [
        {"id": "start", "type": "openai"},
        {"id": "intent", "type": "intent_classification"},
        {"id": "agent", "type": "agents"},
    ]
    intent_edges = [{"source": "start", "target": "intent"}, {"source": "intent", "target": "agent"}]
    g2 = _Graph(intent_nodes, intent_edges, start="start")
    target, path = g2._find_agent_node_via_bfs(intent_nodes[0])
    assert target is None
    assert path[0]["type"] == "intent_classification"

    lonely = _Graph([{"id": "start", "type": "openai"}], [], start="start")
    target, path = lonely._find_agent_node_via_bfs({"id": "start", "type": "openai"})
    assert target is None
    assert path == []
