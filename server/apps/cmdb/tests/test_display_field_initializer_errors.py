"""DisplayFieldInitializer.initialize_all：单模型失败与全局异常。"""
from unittest.mock import patch

import pytest

from apps.cmdb.display_field.initializer import DisplayFieldInitializer

pytestmark = pytest.mark.unit


def test_initialize_all_records_per_model_failure_and_keeps_others():
    init = DisplayFieldInitializer()
    with (
        patch.object(init, "_get_all_models", return_value=[{"model_id": "host"}, {"model_id": "sw"}]),
        patch.object(init, "_preload_mappings"),
        patch.object(init, "_add_display_fields_to_model", side_effect=[RuntimeError("boom"), [{"attr_id": "name"}]]),
        patch.object(init, "_add_display_fields_to_instances", return_value=4),
    ):
        result = init.initialize_all()
    assert result["success"] is False
    assert result["models_processed"] == 1
    assert result["instances_processed"] == 4
    assert "处理模型 host 失败" in result["errors"][0]


def test_initialize_all_records_global_exception():
    init = DisplayFieldInitializer()
    with patch.object(init, "_get_all_models", side_effect=RuntimeError("graph down")):
        result = init.initialize_all()
    assert result["success"] is False
    assert result["models_processed"] == 0
    assert "初始化异常: graph down" in result["errors"][0]


class _BoomGraph:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def query_entity(self, *a, **k):
        raise RuntimeError("query fail")


def test_preload_mappings_swallows_org_user_and_enum_errors():
    init = DisplayFieldInitializer()
    with (
        patch("apps.system_mgmt.models.user.Group.objects.all", side_effect=RuntimeError("no group")),
        patch("apps.system_mgmt.models.user.User.objects.all", side_effect=RuntimeError("no user")),
        patch("apps.cmdb.services.model.ModelManage.parse_attrs", side_effect=RuntimeError("bad attrs")),
    ):
        init._preload_mappings([{"model_id": "host", "attrs": "[]"}])
    assert init._org_map == {}
    assert init._user_map == {}
    assert init._enum_map == {}


def test_add_display_fields_to_instances_query_fail_empty_and_item_error():
    init = DisplayFieldInitializer()
    with patch("apps.cmdb.display_field.initializer.GraphClient", return_value=_BoomGraph()):
        assert init._add_display_fields_to_instances("host", []) == 0

    class _EmptyGraph:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query_entity(self, *a, **k):
            return [], None

    with patch("apps.cmdb.display_field.initializer.GraphClient", return_value=_EmptyGraph()):
        assert init._add_display_fields_to_instances("host", []) == 0

    class _InstGraph:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query_entity(self, *a, **k):
            return [{"inst_id": "i1", "_id": 1, "organization": [1]}, {"inst_id": "i2", "_id": 2}], None

        def set_entity_properties(self, *a, **k):
            raise RuntimeError("write fail")

    with patch("apps.cmdb.display_field.initializer.GraphClient", return_value=_InstGraph()), patch.object(
        init,
        "_build_display_fields_for_instance",
        side_effect=[{"organization_display": "ops"}, {}],
    ):
        assert init._add_display_fields_to_instances("host", [{"attr_id": "organization"}]) == 0


def test_build_display_fields_converts_types_and_falls_back_on_error():
    init = DisplayFieldInitializer()
    init._org_map = {1: "ops"}
    init._user_map = {2: {"username": "admin", "display_name": "管理员"}}
    init._enum_map = {"host.status.active": "启用"}
    attrs = [
        {"attr_id": "cpu", "attr_type": "int"},
        {"attr_id": "missing", "attr_type": "organization"},
        {"attr_id": "organization", "attr_type": "organization"},
        {"attr_id": "owner", "attr_type": "user"},
        {"attr_id": "status", "attr_type": "enum"},
        {"attr_id": "tags", "attr_type": "tag"},
        {"attr_id": "bad", "attr_type": "organization"},
    ]
    instance = {
        "organization": [1],
        "owner": [2],
        "status": "active",
        "tags": ["env:prod", " app:web "],
        "bad": [9],
    }
    with patch.object(init, "_convert_organization", side_effect=["ops", RuntimeError("boom")]):
        out = init._build_display_fields_for_instance(instance, attrs, "host")
    assert out["organization_display"] == "ops"
    assert out["owner_display"] == "管理员(admin)"
    assert out["status_display"] == "启用"
    assert out["tags_display"] == "env:prod, app:web"
    assert out["bad_display"] == "[9]"
    assert "cpu_display" not in out
    assert "missing_display" not in out

    assert init._convert_organization([]) == ""
    assert init._convert_organization(3) == "3"
    assert init._convert_user([]) == ""
    assert init._convert_user([99]) == "99"
    assert init._convert_user([2]) == "管理员(admin)"
    init._user_map[4] = {"username": "plain", "display_name": "  "}
    assert init._convert_user([4]) == "plain"
    assert init._convert_enum("host", "status", "") == ""
    assert init._convert_enum("host", "status", "gone") == "gone"
    assert init._convert_tag([]) == ""
    assert init._convert_tag("raw") == "raw"
    assert init._convert_tag([" a ", "", "b"]) == "a, b"
