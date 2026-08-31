"""system_mgmt.nats_api 纯函数：规则数据、NATS content 规范化、子模块查找。"""
import pytest

from apps.system_mgmt import nats_api

pytestmark = pytest.mark.unit


def test_find_child_module_data_direct_and_nested():
    assert nats_api.find_child_module_data("x", "child") == []
    assert nats_api.find_child_module_data({"host": [{"id": 1}]}, "host") == [{"id": 1}]
    nested = {"cmdb": {"host": [{"id": 2}]}}
    assert nats_api.find_child_module_data(nested, "host") == [{"id": 2}]
    assert nats_api.find_child_module_data({"a": 1}, "missing") == []


def test_process_rule_data_all_permission_and_instance_list():
    assert nats_api.process_rule_data(None) == (True, [])
    assert nats_api.process_rule_data("x") == (True, [])
    has_all, data = nats_api.process_rule_data([{"id": 0}, {"id": 3}])
    assert has_all is True
    assert data == []
    has_all, data = nats_api.process_rule_data([{"id": -1}, {"id": "5"}, {"id": 7}])
    assert has_all is False
    assert [item["id"] for item in data] == ["5", 7]


def test_accumulate_rule_result_merges_team_and_instances():
    result = {}
    nats_api._accumulate_rule_result(result, "host", [{"id": 0}], group_id=9, all_permission_team=[1])
    assert result["host"]["team"] == [1, 9]
    assert result["host"]["instance"] == []
    nats_api._accumulate_rule_result(result, "host", [{"id": 12}], group_id=9, all_permission_team=[1])
    assert {"id": 12} in result["host"]["instance"]


def test_normalize_nats_content_accepts_single_team_and_rejects_bad_payloads():
    ok, err = nats_api._normalize_nats_content(
        {"message": "hello", "team": ["3"], "user_ids": [1, " 2 ", None, ""]}
    )
    assert err is None
    assert ok == {"message": "hello", "team": 3, "user_ids": ["1", "2"]}

    _, err = nats_api._normalize_nats_content("not-json")
    assert err["result"] is False
    _, err = nats_api._normalize_nats_content({"message": "x", "team": [1, 2], "user_ids": []})
    assert "single team id" in err["message"]
    _, err = nats_api._normalize_nats_content({"message": "  ", "team": 1, "user_ids": []})
    assert "message" in err["message"]
    _, err = nats_api._normalize_nats_content({"message": "x", "team": 1, "user_ids": "a"})
    assert "user_ids" in err["message"]


def test_resolve_message_receivers_empty_or_mixed_returns_none():
    assert nats_api._resolve_message_receivers([]) is None
    assert nats_api._resolve_message_receivers(None) is None
    assert nats_api._resolve_message_receivers([1, "alice"]) is None
