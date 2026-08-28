"""FalkorDB 表格字段序列化/反序列化：仅 instance + table 类型字段被转换。"""
import pytest

from apps.cmdb.graph.falkordb import FalkorDBClient

pytestmark = pytest.mark.unit


def test_serialize_table_fields_only_for_instance_lists():
    client = FalkorDBClient()
    props = {"table1": [{"a": 1}], "name": "h1"}
    attrs = [{"attr_id": "table1", "attr_type": "table"}, {"attr_id": "name", "attr_type": "str"}]
    assert client._serialize_table_fields("host", props, attrs) is props
    out = client._serialize_table_fields("instance", props, attrs)
    assert isinstance(out["table1"], str)
    assert '"a": 1' in out["table1"] or '"a":1' in out["table1"].replace(" ", "")
    assert out["name"] == "h1"
    assert client._serialize_table_fields("instance", {}, attrs) == {}
    assert client._serialize_table_fields("instance", {"name": "x"}, None) == {"name": "x"}


def test_deserialize_table_fields_recovers_list_or_empty_on_bad_json():
    client = FalkorDBClient()
    attrs = [{"attr_id": "table1", "attr_type": "table"}]
    rows = [{"table1": '[{"a": 1}]', "name": "h"}, {"table1": "not-json"}]
    out = client._deserialize_table_fields_in_result_list(rows, attrs)
    assert out[0]["table1"] == [{"a": 1}]
    assert out[1]["table1"] == []
    assert client._deserialize_table_fields_in_result_list([], attrs) == []
    unchanged = [{"table1": "x"}]
    assert client._deserialize_table_fields_in_result_list(unchanged, None) is unchanged
