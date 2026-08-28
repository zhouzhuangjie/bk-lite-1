"""CMDB ModelManage：标签自由模式合并选项、默认值清洗、保护字段守卫。"""
from unittest.mock import patch

import pytest

from apps.cmdb.constants.field_constraints import TAG_MODE_FREE
from apps.cmdb.services.model import ModelManage
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.unit


def test_merge_tag_options_from_values_noop_and_appends_new_pairs():
    assert ModelManage.merge_tag_options_from_values("host", []) is None
    with patch.object(ModelManage, "search_model_info", return_value=None):
        assert ModelManage.merge_tag_options_from_values("host", ["env:prod"]) is None

    model_info = {"_id": "nid", "attrs": "[]"}
    attrs = [{"attr_id": "cpu", "attr_type": "str"}]
    with patch.object(ModelManage, "search_model_info", return_value=model_info), patch.object(
        ModelManage, "parse_attrs", return_value=attrs
    ):
        assert ModelManage.merge_tag_options_from_values("host", ["env:prod"]) is None

    tag_attr = {"attr_id": "tag", "attr_type": "tag", "option": {"mode": "strict", "options": []}}
    with patch.object(ModelManage, "search_model_info", return_value=model_info), patch.object(
        ModelManage, "parse_attrs", return_value=[tag_attr]
    ), patch.object(ModelManage, "_is_tag_attr", return_value=True):
        assert ModelManage.merge_tag_options_from_values("host", ["env:prod"]) is None

    tag_attr = {"attr_id": "tag", "attr_type": "tag", "option": {"mode": TAG_MODE_FREE, "options": [{"key": "env", "value": "prod"}]}}
    set_calls = []

    class _G:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def set_entity_properties(self, *args, **kwargs):
            set_calls.append(args)

    with patch.object(ModelManage, "search_model_info", return_value=model_info), patch.object(
        ModelManage, "parse_attrs", return_value=[tag_attr]
    ), patch.object(ModelManage, "_is_tag_attr", return_value=True), patch(
        "apps.cmdb.services.model.GraphClient", return_value=_G()
    ):
        ModelManage.merge_tag_options_from_values("host", ["env:prod", "env:test", "bad", " :x", 1])
    assert set_calls
    dumped = set_calls[0][2]["attrs"]
    assert "test" in dumped


def test_sanitize_non_enum_default_and_guard_protected_attr():
    cleaned = ModelManage.sanitize_attr_default_value({"attr_type": "str", "default_value": ["a", "a", ""]})
    assert cleaned["default_value"] == ["a"]
    with pytest.raises(BaseAppException):
        ModelManage._guard_protected_model_attr("organization", "删除")
