"""Import 剩余导入流：关联创建、校验过滤、Excel 行处理，GraphClient 一律打桩。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.cmdb.constants.field_constraints import TAG_ATTR_ID, TAG_MODE_FREE
from apps.cmdb.utils.Import import Import
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.django_db


def _make(attrs=None, **extra):
    obj = Import.__new__(Import)
    obj.model_id = extra.get("model_id", "host")
    obj.attrs = attrs or []
    obj.exist_items = []
    obj.operator = "admin"
    obj.inst_name_id_map = extra.get("inst_name_id_map", {})
    obj.inst_id_name_map = extra.get(
        "inst_id_name_map",
        {"host": {1: "h1"}, "sw": {2: "s1"}},
    )
    obj.inst_list = []
    obj.model_asso_map = extra.get("model_asso_map", {})
    obj.validation_errors = []
    obj._field_maps = None
    obj.import_result_message = {
        "add": {"success": 0, "error": 0, "data": []},
        "update": {"success": 0, "error": 0, "data": []},
        "asso": {"success": 0, "error": 0, "data": []},
    }
    return obj


def _asso_data():
    return {
        "model_asst_id": "host_conn_sw",
        "src_model_id": "host",
        "dst_model_id": "sw",
        "src_inst_id": 1,
        "dst_inst_id": 2,
    }


def test_instance_association_create_constraint_failure(monkeypatch):
    obj = _make()

    def boom(data):
        raise RuntimeError("mapping violated")

    monkeypatch.setattr("apps.cmdb.services.instance.InstanceManage.check_asso_mapping", boom)
    out = obj.instance_association_create(_asso_data(), operator="admin")
    assert out["success"] is False
    assert out["message"] == "【h1】与【s1】的关联关系【host_conn_sw】创建失败！校验关联约束失败! "


def test_instance_association_create_edge_already_exists(monkeypatch, fake_graph):
    obj = _make()
    monkeypatch.setattr("apps.cmdb.services.instance.InstanceManage.check_asso_mapping", lambda data: None)

    def create_edge(*args, **kwargs):
        raise BaseAppException("edge already exists")

    fake_graph("apps.cmdb.utils.Import", create_edge=create_edge)
    out = obj.instance_association_create(_asso_data(), operator="admin")
    assert out == {
        "success": False,
        "message": "关联 【h1】与【s1】的关联关系【host_conn_sw】 已存在",
    }


def test_instance_association_create_other_graph_error(monkeypatch, fake_graph):
    obj = _make()
    monkeypatch.setattr("apps.cmdb.services.instance.InstanceManage.check_asso_mapping", lambda data: None)

    def create_edge(*args, **kwargs):
        raise BaseAppException("graph down")

    fake_graph("apps.cmdb.utils.Import", create_edge=create_edge)
    out = obj.instance_association_create(_asso_data(), operator="admin")
    assert out == {
        "success": False,
        "message": "【h1】与【s1】的关联关系【host_conn_sw】创建失败！",
    }


def test_instance_association_create_success_writes_change_record(monkeypatch, fake_graph):
    obj = _make()
    monkeypatch.setattr("apps.cmdb.services.instance.InstanceManage.check_asso_mapping", lambda data: None)
    monkeypatch.setattr(
        "apps.cmdb.services.instance.InstanceManage.instance_association_by_asso_id",
        lambda edge_id: {
            "src": {"model_id": "host", "inst_name": "h1"},
            "dst": {"model_id": "sw", "inst_name": "s1"},
        },
    )
    recorded = {}

    def fake_record(*args, **kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr("apps.cmdb.utils.Import.create_change_record_by_asso", fake_record)
    fake_graph("apps.cmdb.utils.Import", create_edge={"_id": 88})
    out = obj.instance_association_create(_asso_data(), operator="admin")
    assert out["success"] is True
    assert out["data"] == {"_id": 88}
    assert out["message"] == "【h1】与【s1】的关联关系【host_conn_sw】创建成功"
    assert recorded["operator"] == "admin"


def test_import_inst_list_delegates_to_save(monkeypatch):
    obj = _make([{"attr_id": "inst_name", "attr_type": "str", "attr_name": "名称"}])
    monkeypatch.setattr(
        Import,
        "format_excel_data",
        lambda self, stream: ([{"inst_name": "h1"}], {}),
    )
    monkeypatch.setattr(Import, "inst_list_save", lambda self, items: [{"success": True, "data": items[0]}])
    result = obj.import_inst_list(b"xlsx")
    assert result == [{"success": True, "data": {"inst_name": "h1"}}]


def test_import_inst_list_support_edit_merges_validation_and_asso(monkeypatch):
    obj = _make([{"attr_id": "inst_name", "attr_type": "str", "attr_name": "名称"}])
    obj.model_asso_map = {"host_conn_sw": {"asst_id": "conn"}}
    obj.validation_errors = ["第4行，字段'名称'的值无效"]
    monkeypatch.setattr(
        Import,
        "format_excel_data",
        lambda self, stream, allowed_org_ids=None: ([{"inst_name": "h1"}], {"host_conn_sw": {"h1": ["s1"]}}),
    )
    monkeypatch.setattr(Import, "inst_list_update", lambda self, items: ([{"success": True, "data": {"inst_name": "h1"}}], []))
    monkeypatch.setattr(Import, "format_import_asso_data", lambda self, asso: None)
    monkeypatch.setattr(
        Import,
        "add_asso_data",
        lambda self, asso: [{"success": False, "message": "创建关联失败: boom"}],
    )
    add_r, update_r, asso_r = obj.import_inst_list_support_edit(b"xlsx", allowed_org_ids=[1])
    assert add_r[0] == {"success": False, "data": {}, "message": "第4行，字段'名称'的值无效"}
    assert add_r[1]["success"] is True
    assert asso_r[0]["message"] == "创建关联失败: boom"
    assert obj.import_result_message["add"]["error"] == 1
    assert obj.import_result_message["add"]["success"] == 1
    assert obj.import_result_message["asso"]["error"] == 1


def test_prepare_instances_for_save_skips_invalid_and_keeps_valid(monkeypatch):
    obj = _make([{"attr_id": "inst_name", "attr_type": "str", "attr_name": "名称"}])
    monkeypatch.setattr(
        "apps.cmdb.validators.FieldValidator.validate_instance_data",
        lambda data, attrs: [{"field_name": "名称", "error": "必填"}] if data["inst_name"] == "bad" else [],
    )
    monkeypatch.setattr(
        "apps.cmdb.display_field.DisplayFieldHandler.build_display_fields",
        lambda mid, info, attrs: {**info, "_display": info["inst_name"]},
    )
    out = obj._prepare_instances_for_save([{"inst_name": "bad"}, {"inst_name": "ok"}])
    assert out == [{"inst_name": "ok", "_display": "ok"}]
    assert obj.validation_errors == ["实例 bad，字段 '名称'：必填"]


def test_process_excel_row_records_cell_error_and_skips_empty():
    obj = _make(
        [
            {"attr_id": "inst_name", "attr_type": "str", "attr_name": "名称"},
            {"attr_id": "count", "attr_type": "int", "attr_name": "数量"},
        ]
    )
    maps = obj._build_field_maps()
    cells = [SimpleNamespace(value="h1"), SimpleNamespace(value="bad-int")]
    item, has_data, has_errors = obj._process_excel_row(cells, ["inst_name", "count"], 4, maps, None, {})
    assert has_data is True
    assert has_errors is True
    assert item["inst_name"] == "h1"
    assert "count" not in item
    assert "格式错误" in obj.validation_errors[0]


def test_process_excel_row_collects_association_column():
    obj = _make([{"attr_id": "inst_name", "attr_type": "str", "attr_name": "名称"}])
    maps = obj._build_field_maps()
    asso = {"host_conn_sw": {}}
    cells = [SimpleNamespace(value="h1"), SimpleNamespace(value="s1,s2")]
    item, has_data, has_errors = obj._process_excel_row(
        cells, ["inst_name", "host_conn_sw"], 4, maps, None, asso
    )
    assert has_data is True
    assert has_errors is False
    assert asso["host_conn_sw"] == {"h1": ["s1", "s2"]}
    assert "host_conn_sw" not in item


def test_normalize_and_merge_tag_records_free_mode_merges(monkeypatch):
    obj = _make(
        [
            {
                "attr_id": TAG_ATTR_ID,
                "attr_type": "tag",
                "attr_name": "标签",
                "option": {"mode": TAG_MODE_FREE},
            }
        ]
    )
    merged = []
    monkeypatch.setattr(
        "apps.cmdb.services.model.ModelManage.merge_tag_options_from_values",
        lambda model_id, values: merged.extend(values),
    )
    out = obj._normalize_and_merge_tag_records(
        [
            {"inst_name": "h1", TAG_ATTR_ID: ["env:prod"]},
            {"inst_name": "h2", TAG_ATTR_ID: ["tier:core"]},
        ]
    )
    assert [row[TAG_ATTR_ID] for row in out] == [["env:prod"], ["tier:core"]]
    assert set(merged) == {"env:prod", "tier:core"}


def test_build_field_maps_skips_file_attr(monkeypatch):
    monkeypatch.setattr("apps.cmdb.utils.Import.is_file_attr_type", lambda attr_type: attr_type == "file")
    obj = _make(
        [
            {"attr_id": "attach", "attr_type": "file", "attr_name": "附件"},
            {"attr_id": "name", "attr_type": "str", "attr_name": "名称"},
        ]
    )
    maps = obj._build_field_maps()
    assert "attach" not in maps["attr_name_map"]
    assert maps["attr_name_map"]["name"] == "名称"


def test_process_org_user_field_user_comma_and_invalid():
    obj = _make(
        [
            {
                "attr_id": "owner",
                "attr_type": "user",
                "attr_name": "负责人",
                "option": [{"id": "alice", "name": "alice"}],
            }
        ]
    )
    maps = obj._build_field_maps()
    ids, err, provided = obj._process_org_user_field("owner", "alice,bob", 3, maps, None)
    assert ids is None
    assert provided is False
    assert err == "第3行，字段'负责人'的值'['bob']'无效"

    ids, err, provided = obj._process_org_user_field("owner", "alice", 3, maps, None)
    assert ids == ["alice"]
    assert err is None


def test_get_model_asso_map_indexes_by_asst_id(monkeypatch):
    monkeypatch.setattr(
        "apps.cmdb.services.model.ModelManage.model_association_search",
        lambda mid: [{"model_asst_id": "host_conn_sw", "asst_id": "conn"}],
    )
    obj = _make([])
    assert obj.get_model_asso_map() == {"host_conn_sw": {"model_asst_id": "host_conn_sw", "asst_id": "conn"}}


def test_add_asso_data_records_create_exception(monkeypatch):
    obj = _make()
    obj.model_asso_map = {
        "host_conn_sw": {"asst_id": "conn", "src_model_id": "host", "dst_model_id": "sw"}
    }
    obj.inst_name_id_map = {"host": {"h1": 1}, "sw": {"s1": 2}}
    obj.inst_id_name_map = {"host": {1: "h1"}, "sw": {2: "s1"}}

    def boom(self, data, operator):
        raise RuntimeError("graph timeout")

    monkeypatch.setattr(Import, "instance_association_create", boom)
    result = obj.add_asso_data({"host_conn_sw": {"h1": ["s1"]}})
    assert result == [{"success": False, "message": "创建关联失败: graph timeout"}]
