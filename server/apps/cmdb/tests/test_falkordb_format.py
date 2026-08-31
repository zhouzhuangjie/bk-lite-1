"""FalkorDB 结果格式化：字典/计数/节点属性/路径/边列表。"""
from types import SimpleNamespace

import pytest

from apps.cmdb.graph.falkordb_format import FormatDBResult

pytestmark = pytest.mark.unit


def test_empty_result_and_count_helpers():
    fmt = FormatDBResult(SimpleNamespace())
    assert fmt.to_list_of_dicts() == []
    assert fmt.get_first_record() == {}
    assert fmt.get_column("x") == []
    assert fmt.count() == 0
    assert fmt.is_empty() is True
    assert fmt.get_statistics() == {}
    assert "records=0" in str(fmt)


def test_format_nodes_paths_counts_and_edges():
    node = SimpleNamespace(id=1, labels=["host"], properties={"name": "h1", "model_id": "host"})
    path = SimpleNamespace(nodes=[node], edges=[])
    result = SimpleNamespace(
        header=[("type", "n"), ("type", "p")],
        result_set=[[node, path]],
        get_statistics=lambda: SimpleNamespace(nodes_created=2, relationships_created=1),
    )
    fmt = FormatDBResult(result)
    rows = fmt.to_list_of_dicts()
    assert rows[0]["_id"] == 1
    assert rows[0]["_labels"] == "host"
    assert rows[0]["name"] == "h1"
    assert rows[1]["type"] == "path"
    assert rows[1]["nodes"][0]["name"] == "h1"
    assert fmt.to_json()
    stats = fmt.get_statistics()
    assert stats["nodes_created"] == 2
    assert stats["relationships_created"] == 1
    assert fmt.get_first_record()["_id"] == 1

    counted = FormatDBResult(SimpleNamespace(result_set=[[["k"], 3], [{"a": 1}, 2]]))
    assert counted.to_result_of_count()["k"] == 3
    assert '{"a": 1}' in counted.to_result_of_count()

    edge = SimpleNamespace(
        id=9,
        properties={"src_model_id": "host", "dst_model_id": "svc"},
    )
    src = SimpleNamespace(id=1, properties={"model_id": "host", "name": "h"})
    dst = SimpleNamespace(id=2, properties={"model_id": "svc", "name": "s"})
    rel = SimpleNamespace(_edges=[edge], _nodes=[src, dst])
    edges = FormatDBResult(SimpleNamespace(result_set=[[rel]])).format_edge_to_list()
    assert edges[0]["edge"]["_id"] == 9
    assert edges[0]["src"]["name"] == "h"
    assert edges[0]["dst"]["name"] == "s"
    assert FormatDBResult(SimpleNamespace(result_set=[[SimpleNamespace(_edges=[])]])).format_edge_to_list() == []
