"""format_type 剩余参数化格式化：钉死 Cypher 片段与参数名。"""
import pytest

from apps.cmdb.graph import format_type as ft

pytestmark = pytest.mark.unit


def test_format_bool_and_time_params():
    collector = ft.ParameterCollector()
    assert ft.format_bool_params({"field": "active", "value": True}, collector) == "n.active = $bool1"
    out = ft.format_time_params({"field": "ts", "start": "2026-01-01", "end": "2026-01-02"}, collector)
    assert out == "n.ts >= $time_start2 AND n.ts <= $time_end3"
    assert collector.get_params() == {"bool1": True, "time_start2": "2026-01-01", "time_end3": "2026-01-02"}


def test_format_str_neq_in_and_user_in_params():
    collector = ft.ParameterCollector()
    assert ft.format_str_neq_params({"field": "name", "value": "host"}, collector) == "n.name <> $str1"
    assert ft.format_str_in_params({"field": "name", "value": ["a", "b"]}, collector) == "n.name IN $str_list2"
    assert ft.format_user_in_params({"field": "owner", "value": ["u1"]}, collector) == "n.owner IN $user_list3"
    assert collector.get_params()["str1"] == "host"
    assert collector.get_params()["str_list2"] == ["a", "b"]


def test_format_str_like_params_case_sensitive_and_insensitive():
    collector = ft.ParameterCollector()
    sensitive = ft.format_str_like_params({"field": "name", "value": "Host"}, collector)
    assert sensitive == "n.name CONTAINS $str1"
    insensitive = ft.format_str_like_params(
        {"field": "name", "value": "Host", "case_sensitive": False}, collector
    )
    assert insensitive == "toLower(n.name) CONTAINS toLower($str2)"


def test_format_int_ops_params():
    collector = ft.ParameterCollector()
    assert ft.format_int_gt_params({"field": "c", "value": 3}, collector) == "n.c > $int1"
    assert ft.format_int_lt_params({"field": "c", "value": 3}, collector) == "n.c < $int2"
    assert ft.format_int_neq_params({"field": "c", "value": 3}, collector) == "n.c <> $int3"
    assert ft.format_int_in_params({"field": "c", "value": [1, 2]}, collector) == "n.c IN $int_list4"


def test_format_id_in_and_list_any_params():
    collector = ft.ParameterCollector()
    assert ft.format_id_in_params({"value": [115, 116]}, collector) == "ID(n) IN $ids1"
    assert collector.get_params()["ids1"] == [115, 116]
    out = ft.format_list_any_params({"field": "tags", "value": [2, 5]}, collector)
    assert out == "ANY(x IN $list2 WHERE x IN n.tags)"


def test_compile_tag_exact_match_query_strips_blank_and_keeps_accurate():
    assert ft.compile_tag_exact_match_query("tags", []) == []
    blanks_only = ft.compile_tag_exact_match_query("tags", ["", "  "])
    assert blanks_only == [
        {"field": "tags", "type": "list_any[]", "value": [], "accurate": True}
    ]
    out = ft.compile_tag_exact_match_query("tags", ["prod", "  ", "core"])
    assert out == [
        {
            "field": "tags",
            "type": "list_any[]",
            "value": ["prod", "core"],
            "accurate": True,
        }
    ]
