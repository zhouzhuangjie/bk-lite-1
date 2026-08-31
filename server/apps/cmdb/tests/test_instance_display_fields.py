"""InstanceManage 展示字段回填与唯一规则校验映射。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.cmdb.display_field.constants import DISPLAY_SUFFIX
from apps.cmdb.services.instance import InstanceManage

pytestmark = pytest.mark.unit


def test_apply_display_fields_converts_supported_types():
    attrs = [
        {"attr_id": "org", "attr_type": "organization"},
        {"attr_id": "owner", "attr_type": "user"},
        {"attr_id": "status", "attr_type": "enum", "option": [{"id": "on", "name": "在线"}]},
        {"attr_id": "tags", "attr_type": "tag"},
        {"attr_id": "rows", "attr_type": "table"},
        {"attr_id": "name", "attr_type": "str"},
        {"attr_id": "missing", "attr_type": "organization"},
    ]
    update_attr = {
        "org": [1],
        "owner": ["alice"],
        "status": "on",
        "tags": ["prod"],
        "rows": [{"a": 1}],
        "name": "h1",
    }
    with (
        patch("apps.cmdb.display_field.DisplayFieldConverter.convert_organization", return_value="技术部"),
        patch("apps.cmdb.display_field.DisplayFieldConverter.convert_user", return_value="Alice(alice)"),
        patch("apps.cmdb.display_field.DisplayFieldConverter.convert_enum", return_value="在线"),
        patch("apps.cmdb.display_field.DisplayFieldConverter.convert_tag", return_value="prod"),
        patch("apps.cmdb.display_field.DisplayFieldConverter.convert_table", return_value="1 行"),
    ):
        InstanceManage._apply_display_fields_to_update(attrs, update_attr)
    assert update_attr[f"org{DISPLAY_SUFFIX}"] == "技术部"
    assert update_attr[f"owner{DISPLAY_SUFFIX}"] == "Alice(alice)"
    assert update_attr[f"status{DISPLAY_SUFFIX}"] == "在线"
    assert update_attr[f"tags{DISPLAY_SUFFIX}"] == "prod"
    assert update_attr[f"rows{DISPLAY_SUFFIX}"] == "1 行"
    assert f"name{DISPLAY_SUFFIX}" not in update_attr
    assert f"missing{DISPLAY_SUFFIX}" not in update_attr


def test_build_unique_rule_check_attr_map_includes_context(monkeypatch):
    attrs = [
        {"attr_id": "ip", "attr_name": "IP", "is_only": True, "is_required": True, "editable": True},
        {"attr_id": "hostname", "attr_name": "主机名", "is_display_field": True},
    ]
    ctx = SimpleNamespace(unique_rules=[{"attrs": ["ip"]}], attrs_by_id={"ip": attrs[0]})
    monkeypatch.setattr("apps.cmdb.services.instance.build_unique_rule_context", lambda model_id: ctx)
    out = InstanceManage._build_unique_rule_check_attr_map("host", attrs, for_update=True)
    assert out["is_only"] == {"ip": "IP"}
    assert out["is_required"] == {"ip": "IP"}
    assert out["editable"] == {"ip": "IP", "hostname": "主机名"}
    assert out["unique_rules"] == [{"attrs": ["ip"]}]
    assert out["attrs_by_id"]["ip"]["attr_id"] == "ip"
