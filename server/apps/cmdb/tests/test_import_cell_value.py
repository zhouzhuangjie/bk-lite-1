"""Import._process_cell_value：类型转换 / 表格 / 标签 / 组织 / 枚举分支。"""
import pytest

from apps.cmdb.constants.constants import ENUM, ORGANIZATION

pytestmark = pytest.mark.unit


@pytest.fixture
def make_import(monkeypatch):
    from apps.cmdb.utils.Import import Import

    monkeypatch.setattr(Import, "get_model_asso_map", lambda self: {})

    def _factory(attrs):
        return Import(model_id="host", attrs=attrs, exist_items=[], operator="admin")

    return _factory


def test_process_cell_value_routes_conversion_table_tag_org_enum(make_import):
    attrs = [
        {"attr_id": "count", "attr_name": "数量", "attr_type": "int"},
        {"attr_id": "spec", "attr_name": "规格", "attr_type": "table"},
        {"attr_id": "tags", "attr_name": "标签", "attr_type": "tag"},
        {
            "attr_id": "org",
            "attr_name": "组织",
            "attr_type": ORGANIZATION,
            "option": [{"id": 1, "name": "运维"}],
        },
        {
            "attr_id": "status",
            "attr_name": "状态",
            "attr_type": ENUM,
            "option": [{"id": "on", "name": "运行"}],
            "enum_select_mode": "single",
        },
        {"attr_id": "name", "attr_name": "名称", "attr_type": "str"},
    ]
    imp = make_import(attrs)
    maps = imp._build_field_maps()
    item = {}

    cont, err, _org = imp._process_cell_value("count", "7", 1, maps, set(), item)
    assert cont is True and err is None and item["count"] == 7

    cont, err, _org = imp._process_cell_value("count", "bad", 2, maps, set(), item)
    assert cont is True and "格式错误" in err

    cont, err, _org = imp._process_cell_value("spec", '[{"a":1}]', 1, maps, set(), item)
    assert item["spec"] == [{"a": 1}] and err is None

    cont, err, _org = imp._process_cell_value("tags", ["prod", "core"], 1, maps, set(), item)
    assert err is None and item["tags"] == ["prod", "core"]

    imp._process_org_user_field = lambda key, value, row_index, field_maps, allowed_org_set: ([1], None, True)
    cont, err, org_flag = imp._process_cell_value("org", "运维", 1, maps, {1}, item)
    assert cont is True and err is None and org_flag is True
    assert item["org"] == [1]

    cont, err, _org = imp._process_cell_value("status", "运行", 1, maps, set(), item)
    assert err is None
    assert item["status"] == ["on"]

    cont, err, _org = imp._process_cell_value("name", "host-1", 1, maps, set(), item)
    assert cont is True and err is None and item["name"] == "host-1"
