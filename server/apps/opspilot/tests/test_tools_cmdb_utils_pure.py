"""CMDB 工具纯函数单元测试 (cmdb/utils)。

覆盖配置提取、用户组 id 解析、查询条件归一化、响应包装、写权限护栏、JSON 序列化。
不触 DB(使用轻量假 user 对象,仅访问属性)。
"""

from types import SimpleNamespace

import pytest

from apps.opspilot.metis.llm.tools.cmdb import utils as cu


class TestGetConfigurable:
    def test_none_returns_empty(self):
        assert cu._get_configurable(None) == {}

    def test_dict_config(self):
        assert cu._get_configurable({"configurable": {"a": 1}}) == {"a": 1}

    def test_object_config(self):
        cfg = SimpleNamespace(configurable={"b": 2})
        assert cu._get_configurable(cfg) == {"b": 2}


class TestGetUserGroupIds:
    def test_empty(self):
        assert cu._get_user_group_ids(SimpleNamespace(group_list=[])) == []

    def test_list_of_dicts(self):
        user = SimpleNamespace(group_list=[{"id": "1"}, {"id": 2}, {"name": "no-id"}])
        assert cu._get_user_group_ids(user) == [1, 2]

    def test_list_of_ints(self):
        user = SimpleNamespace(group_list=[3, "4"])
        assert cu._get_user_group_ids(user) == [3, 4]

    def test_missing_attr(self):
        assert cu._get_user_group_ids(SimpleNamespace()) == []


class TestNormalizeQueryList:
    def test_none(self):
        assert cu.normalize_query_list(None) == []

    def test_single_dict_wrapped(self):
        out = cu.normalize_query_list({"field": "name", "type": "str=", "value": "x"})
        assert out == [{"field": "name", "type": "str=", "value": "x"}]

    def test_non_list_non_dict(self):
        assert cu.normalize_query_list("string") == []

    def test_missing_field_or_type_dropped(self):
        out = cu.normalize_query_list([{"field": "a"}, {"type": "str="}])
        assert out == []

    def test_time_type_needs_start_end(self):
        ok = {"field": "t", "type": "time", "start": "s", "end": "e"}
        assert cu.normalize_query_list([ok]) == [ok]
        bad = {"field": "t", "type": "time", "start": "s"}
        assert cu.normalize_query_list([bad]) == []

    def test_empty_string_value_dropped(self):
        assert cu.normalize_query_list([{"field": "a", "type": "str=", "value": ""}]) == []

    def test_empty_list_value_dropped(self):
        assert cu.normalize_query_list([{"field": "a", "type": "in", "value": []}]) == []

    def test_none_value_dropped(self):
        assert cu.normalize_query_list([{"field": "a", "type": "str=", "value": None}]) == []

    def test_nested_lists_walked(self):
        nested = [[{"field": "a", "type": "str=", "value": "1"}], {"field": "b", "type": "str=", "value": "2"}]
        out = cu.normalize_query_list(nested)
        assert {c["field"] for c in out} == {"a", "b"}

    def test_value_zero_kept(self):
        out = cu.normalize_query_list([{"field": "a", "type": "int=", "value": 0}])
        assert out == [{"field": "a", "type": "int=", "value": 0}]


class TestWrappers:
    def test_wrap_success(self):
        assert cu.wrap_success([1, 2]) == {"success": True, "data": [1, 2]}

    def test_wrap_error(self):
        assert cu.wrap_error("nope") == {"success": False, "error": "nope"}

    def test_to_json_safe_unicode(self):
        assert cu.to_json_safe({"名": "值"}) == '{"名": "值"}'


class TestEnsureWriteAllowed:
    def test_disabled_raises(self):
        with pytest.raises(ValueError, match="disabled"):
            cu.ensure_write_allowed(SimpleNamespace(is_superuser=True), allow_write=False)

    def test_non_superuser_raises(self):
        with pytest.raises(ValueError, match="superuser"):
            cu.ensure_write_allowed(SimpleNamespace(is_superuser=False), allow_write=True)

    def test_superuser_with_write_ok(self):
        # 不应抛异常
        cu.ensure_write_allowed(SimpleNamespace(is_superuser=True), allow_write=True)


class TestResolveAllowWrite:
    def test_explicit_overrides(self):
        assert cu._resolve_allow_write({"configurable": {"allow_write": True}}, allow_write=False) is False

    def test_from_configurable(self):
        assert cu._resolve_allow_write({"configurable": {"allow_write": True}}, allow_write=None) is True

    def test_default_false(self):
        assert cu._resolve_allow_write({}, allow_write=None) is False


class TestGetUserFromConfigAndTeam:
    def test_user_id_required_and_must_be_int(self):
        with pytest.raises(ValueError, match="user_id is required"):
            cu._get_user_from_config({})
        with pytest.raises(ValueError, match="user_id must be an integer"):
            cu._get_user_from_config({"configurable": {"user_id": "abc"}})

    def test_user_id_not_found(self, monkeypatch):
        class _QS:
            def filter(self, **kwargs):
                return self

            def first(self):
                return None

        monkeypatch.setattr(cu, "get_user_model", lambda: SimpleNamespace(objects=_QS()))
        with pytest.raises(ValueError, match="user_id not found"):
            cu._get_user_from_config({"configurable": {"user_id": "9"}})

    def test_resolve_team_from_group_or_default(self, monkeypatch):
        team, include = cu._resolve_team_context(SimpleNamespace(group_list=[{"id": 7}]), {}, None, None)
        assert team == 7
        assert include is False
        monkeypatch.setattr(cu, "get_default_group_id", lambda: [3])
        team, include = cu._resolve_team_context(SimpleNamespace(group_list=[]), {}, None, True)
        assert team == 3
        assert include is True
        team, include = cu._resolve_team_context(
            SimpleNamespace(group_list=[]), {"configurable": {"team_id": 8, "include_children": True}}, None, None
        )
        assert team == 8
        assert include is True


class TestPermissionGuards:
    def test_ensure_instance_permission_skips_creator(self):
        cu.ensure_instance_permission(SimpleNamespace(username="alice"), {"_creator": "alice", "_id": 1}, {}, "View")

    def test_ensure_instance_and_model_denied(self, monkeypatch):
        monkeypatch.setattr(cu.CmdbRulesFormatUtil, "has_object_permission", staticmethod(lambda **k: False))
        monkeypatch.setattr(cu, "get_default_group_id", lambda: [1])
        with pytest.raises(ValueError, match="insufficient instance permission"):
            cu.ensure_instance_permission(SimpleNamespace(username="bob"), {"_id": 9, "model_id": "host"}, {}, "View")
        with pytest.raises(ValueError, match="insufficient model permission"):
            cu.ensure_model_permission(SimpleNamespace(), {"model_id": "host"}, {}, "View")

    def test_build_user_groups_falls_back_to_current_team(self, monkeypatch):
        monkeypatch.setattr(cu, "_get_user_group_ids", lambda user: [])
        monkeypatch.setattr(cu, "format_groups_params", lambda ids: [{"id": i} for i in ids])
        assert cu.build_user_groups(SimpleNamespace(), 5, False) == [{"id": 5}]
        monkeypatch.setattr(
            cu.GroupUtils, "get_user_authorized_child_groups", staticmethod(lambda *a, **k: [5, 6])
        )
        monkeypatch.setattr(cu, "_get_user_group_ids", lambda user: [5])
        assert cu.build_user_groups(SimpleNamespace(), 5, True) == [{"id": 5}, {"id": 6}]
