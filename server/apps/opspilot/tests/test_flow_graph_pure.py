"""ChatFlow FlowGraphMixin：入口识别、BFS 找 agents、意图/条件边路由。"""
import pytest

from apps.opspilot.utils.chat_flow_utils.engine.flow_graph import FlowGraphMixin

pytestmark = pytest.mark.unit


class _Graph(FlowGraphMixin):
    def __init__(self, nodes, edges):
        self.nodes = nodes
        self.edges = edges
        self._node_map = {n["id"]: n for n in nodes}
        self.start_node_id = nodes[0]["id"] if nodes else None


def _node(node_id, node_type, **extra):
    data = {"id": node_id, "type": node_type, "data": extra}
    return data


def test_identify_entry_nodes_are_those_without_incoming_edges():
    graph = _Graph(
        [_node("a", "entry"), _node("b", "agents"), _node("c", "exit")],
        [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
    )
    assert set(graph._identify_entry_nodes()) == {"a"}


def test_parse_nodes_and_edges_read_flow_json():
    graph = _Graph([], [])
    assert graph._parse_nodes({"nodes": [{"id": "n"}]}) == [{"id": "n"}]
    assert graph._parse_edges({"edges": [{"source": "a"}]}) == [{"source": "a"}]


def test_bfs_returns_first_agents_node_and_intermediate_path():
    graph = _Graph(
        [_node("start", "entry"), _node("mid", "function"), _node("agent", "agents")],
        [{"source": "start", "target": "mid"}, {"source": "mid", "target": "agent"}],
    )
    found, path = graph._find_agent_node_via_bfs(_node("start", "entry"))
    assert found["id"] == "agent"
    assert [n["id"] for n in path] == ["mid"]


def test_bfs_stops_at_intent_classification_for_dynamic_routing():
    graph = _Graph(
        [_node("start", "entry"), _node("intent", "intent_classification"), _node("agent", "agents")],
        [{"source": "start", "target": "intent"}, {"source": "intent", "target": "agent", "sourceHandle": "alarm"}],
    )
    found, path = graph._find_agent_node_via_bfs(_node("start", "entry"))
    assert found is None
    assert path[0]["id"] == "intent"


def test_bfs_returns_none_when_no_agents_reachable():
    graph = _Graph(
        [_node("start", "entry"), _node("end", "exit")],
        [{"source": "start", "target": "end"}],
    )
    found, path = graph._find_agent_node_via_bfs(_node("start", "entry"))
    assert found is None
    assert path == []


def test_find_agent_by_intent_matches_source_handle():
    graph = _Graph(
        [_node("intent", "intent_classification"), _node("alarm", "agents"), _node("other", "agents")],
        [
            {"source": "intent", "target": "alarm", "sourceHandle": "alarm_helper"},
            {"source": "intent", "target": "other", "sourceHandle": "other"},
        ],
    )
    assert graph._find_agent_by_intent("intent", "alarm_helper")["id"] == "alarm"
    assert graph._find_agent_by_intent("intent", "missing") is None


def test_should_follow_edge_routes_by_intent_result():
    graph = _Graph([_node("intent", "intent_classification"), _node("a", "agents")], [])
    edge = {"source": "intent", "target": "a", "sourceHandle": "alarm"}
    assert graph._should_follow_edge(edge, {"success": True, "data": {"intent_result": "alarm"}}) is True
    assert graph._should_follow_edge(edge, {"success": True, "data": {"intent_result": "other"}}) is False
    assert graph._should_follow_edge({"source": "intent", "target": "a"}, {"success": True, "data": {"intent_result": "alarm"}}) is False


def test_should_follow_edge_routes_condition_nodes_by_boolean_handle():
    graph = _Graph([_node("cond", "condition"), _node("yes", "agents"), _node("no", "agents")], [])
    true_edge = {"source": "cond", "target": "yes", "sourceHandle": "true"}
    false_edge = {"source": "cond", "target": "no", "sourceHandle": "false"}
    yes = {"success": True, "data": {"condition_result": True}}
    no = {"success": True, "data": {"condition_result": False}}
    assert graph._should_follow_edge(true_edge, yes) is True
    assert graph._should_follow_edge(false_edge, yes) is False
    assert graph._should_follow_edge(true_edge, no) is False
    assert graph._should_follow_edge(false_edge, no) is True
    assert graph._should_follow_edge(true_edge, {"success": True, "data": {}}) is False


def test_should_follow_edge_does_not_treat_literal_true_intent_as_condition():
    graph = _Graph([_node("intent", "intent_classification"), _node("a", "agents")], [])
    edge = {"source": "intent", "target": "a", "sourceHandle": "true"}
    assert graph._should_follow_edge(edge, {"success": True, "data": {"intent_result": "true"}}) is True


def test_get_next_nodes_returns_followed_targets():
    graph = _Graph(
        [_node("start", "function"), _node("a", "agents"), _node("b", "agents")],
        [
            {"id": "e1", "source": "start", "target": "a"},
            {"id": "e2", "source": "start", "target": "b"},
            {"id": "e3", "source": "a", "target": "b"},
        ],
    )
    assert graph._get_next_nodes("start", {"success": True, "data": {}}) == ["a", "b"]
    assert graph._get_next_nodes("b", {"success": True, "data": {}}) == []
