"""CMDB 字段校验剩余：标签、表格、数字类型、自定义正则与标识符。"""
from unittest.mock import patch

import pytest

from apps.cmdb.constants.field_constraints import TAG_MAX_PAIRS
from apps.cmdb.validators.field_validator import (
    FieldValidator,
    IdentifierValidator,
    normalize_enum_values,
    normalize_tag_field_option,
    normalize_tag_input_values,
    timeout_handler,
    validate_enum_values,
    validate_tag_values,
    ValidationTimeoutError,
)
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.unit


def test_tag_option_and_values_reject_invalid_shapes():
    with pytest.raises(BaseAppException, match="必须是对象"):
        normalize_tag_field_option(["x"])
    with pytest.raises(BaseAppException, match="仅支持 free 或 strict"):
        normalize_tag_field_option({"mode": "other"})
    with pytest.raises(BaseAppException, match="options 必须是数组"):
        normalize_tag_field_option({"options": {}})
    with pytest.raises(BaseAppException, match="第1项必须是对象"):
        normalize_tag_field_option({"options": ["env"]})
    with pytest.raises(BaseAppException, match="key 不能为空"):
        normalize_tag_field_option({"options": [{"key": "", "value": "prod"}]})
    with pytest.raises(BaseAppException, match="value 不能为空"):
        normalize_tag_field_option({"options": [{"key": "env", "value": ""}]})
    with pytest.raises(BaseAppException, match="空格、冒号或换行符"):
        normalize_tag_field_option({"options": [{"key": "env", "value": "pro d"}]})

    cfg = normalize_tag_field_option(
        {"mode": "strict", "options": [{"key": "env", "value": "prod"}, {"key": "env", "value": "prod"}]}
    )
    assert len(cfg.options) == 1
    result = validate_tag_values("env:prod", cfg)
    assert result.errors == ["标签值必须是数组"]
    result = validate_tag_values(["", "env", "env: ", "env:stage", "env:prod", "env:prod"], cfg)
    assert any("必须为 key:value" in e for e in result.errors)
    assert any("不合法" in e for e in result.errors)
    assert any("不在候选范围内" in e for e in result.errors)
    assert [item.raw for item in result.normalized_values] == ["env:prod"]

    many = [f"k{i}:v{i}" for i in range(TAG_MAX_PAIRS + 1)]
    overflow = validate_tag_values(many, normalize_tag_field_option({"mode": "free"}))
    assert any("最多允许" in e for e in overflow.errors)


def test_normalize_tag_and_enum_input_tokens():
    assert normalize_tag_input_values(None) == []
    assert normalize_tag_input_values([" env:prod ", ""]) == ["env:prod"]
    assert normalize_tag_input_values("env:prod，app:web\nregion:bj") == ["env:prod", "app:web", "region:bj"]
    with pytest.raises(BaseAppException, match="必须是字符串或字符串数组"):
        normalize_tag_input_values({"env": "prod"})
    assert normalize_enum_values(None) == []
    assert normalize_enum_values([" a ", "", None]) == ["a"]
    assert normalize_enum_values("a，b\nc") == ["a", "b", "c"]
    assert normalize_enum_values(3) == ["3"]
    validate_enum_values(["on"], "single", {"on"}, required=False)
    with pytest.raises(BaseAppException, match="不能为空"):
        validate_enum_values([], "single", {"on"}, required=True, attr_id="status")
    with pytest.raises(BaseAppException, match="只能选择一个值"):
        validate_enum_values(["a", "b"], "single", {"a", "b"}, required=False)
    with pytest.raises(BaseAppException, match="不在有效选项范围内"):
        validate_enum_values(["x"], "multiple", {"on"}, required=False)


def test_string_number_identifier_and_timeout_handler():
    FieldValidator.validate_string(12, {"validation_type": "unrestricted"})
    with pytest.raises(BaseAppException, match="JSON格式校验失败"):
        FieldValidator.validate_string("{", {"validation_type": "json"})
    with pytest.raises(BaseAppException, match="自定义正则表达式不能为空"):
        FieldValidator.validate_string("abc", {"validation_type": "custom", "custom_regex": "  "})
    with pytest.raises(BaseAppException, match="长度不能超过"):
        FieldValidator.validate_string("abc", {"validation_type": "custom", "custom_regex": "a" * 201})
    with pytest.raises(BaseAppException, match="正则表达式格式错误"):
        FieldValidator.validate_string("abc", {"validation_type": "custom", "custom_regex": "("})
    with pytest.raises(BaseAppException, match="未知的校验类型"):
        FieldValidator.validate_string("abc", {"validation_type": "nope"})
    with pytest.raises(BaseAppException, match="不支持的数字类型"):
        FieldValidator.validate_number(1, {}, attr_type="decimal")
    with pytest.raises(BaseAppException, match="不是有效的整数"):
        FieldValidator.validate_number("x", {}, attr_type="int")
    FieldValidator.validate_number(-1, {"min_value": "bad", "max_value": "also-bad"}, attr_type="int")
    assert IdentifierValidator.is_valid("") is False
    assert IdentifierValidator.is_valid("host_ip") is True
    assert "ID" in IdentifierValidator.get_error_message()
    with pytest.raises(ValidationTimeoutError, match="字段校验超时"):
        timeout_handler(None, None)


def test_table_option_and_value_contracts():
    with pytest.raises(BaseAppException, match="必须是数组"):
        FieldValidator.validate_table_option({})
    with pytest.raises(BaseAppException, match="至少需要定义一列"):
        FieldValidator.validate_table_option([])
    with pytest.raises(BaseAppException, match="必须是对象"):
        FieldValidator.validate_table_option(["col"])
    with pytest.raises(BaseAppException, match="缺少 column_id"):
        FieldValidator.validate_table_option([{"column_name": "n", "column_type": "str", "order": 1}])
    with pytest.raises(BaseAppException, match="缺少 column_name"):
        FieldValidator.validate_table_option([{"column_id": "name", "column_type": "str", "order": 1}])
    with pytest.raises(BaseAppException, match="缺少 column_type"):
        FieldValidator.validate_table_option([{"column_id": "name", "column_name": "名称", "order": 1}])
    with pytest.raises(BaseAppException, match="缺少 order"):
        FieldValidator.validate_table_option([{"column_id": "name", "column_name": "名称", "column_type": "str"}])
    with pytest.raises(BaseAppException, match="列ID"):
        FieldValidator.validate_table_option(
            [{"column_id": "Bad Id", "column_name": "名称", "column_type": "str", "order": 1}]
        )
    with pytest.raises(BaseAppException, match="重复"):
        FieldValidator.validate_table_option(
            [
                {"column_id": "name", "column_name": "A", "column_type": "str", "order": 1},
                {"column_id": "name", "column_name": "B", "column_type": "str", "order": 2},
            ]
        )
    with pytest.raises(BaseAppException, match="只能是 'str' 或 'number'"):
        FieldValidator.validate_table_option(
            [{"column_id": "name", "column_name": "名称", "column_type": "bool", "order": 1}]
        )
    with pytest.raises(BaseAppException, match="order 必须 >= 1"):
        FieldValidator.validate_table_option(
            [{"column_id": "name", "column_name": "名称", "column_type": "str", "order": 0}]
        )
    with pytest.raises(BaseAppException, match="order 必须是整数"):
        FieldValidator.validate_table_option(
            [{"column_id": "name", "column_name": "名称", "column_type": "str", "order": "x"}]
        )

    option = [{"column_id": "name", "column_name": "名称", "column_type": "str", "order": 1}]
    FieldValidator.validate_table_value(None, option)
    with pytest.raises(BaseAppException, match="不是合法的 JSON"):
        FieldValidator.validate_table_value("{", option)
    with pytest.raises(BaseAppException, match="必须是 JSON 字符串或数组"):
        FieldValidator.validate_table_value({"name": "a"}, option)
    with pytest.raises(BaseAppException, match="解析后必须是数组"):
        FieldValidator.validate_table_value("{}", option)
    with pytest.raises(BaseAppException, match="必须是对象"):
        FieldValidator.validate_table_value(["row"], option)
    with patch("apps.cmdb.validators.field_validator.TABLE_MAX_ROWS", 1):
        with pytest.raises(BaseAppException, match="最多允许 1 行"):
            FieldValidator.validate_table_value([{"name": "a"}, {"name": "b"}], option)
    with pytest.raises(BaseAppException, match="未定义的列"):
        FieldValidator.validate_table_value([{"size": 1}], option)
    with patch("apps.cmdb.validators.field_validator.TABLE_MAX_CELL_LENGTH", 2):
        with pytest.raises(BaseAppException, match="超过最大长度"):
            FieldValidator.validate_table_value([{"name": "abc"}], option)

    number_option = [{"column_id": "size", "column_name": "大小", "column_type": "number", "order": 1}]
    FieldValidator.validate_table_value([{"size": ""}], number_option)
    with pytest.raises(BaseAppException, match="不是有效的数字"):
        FieldValidator.validate_table_value([{"size": "x"}], number_option)


def test_user_time_empty_and_enum_empty_pass():
    FieldValidator.validate_user_value(None)
    with pytest.raises(BaseAppException, match="必须是数组"):
        FieldValidator.validate_user_value("alice")
    FieldValidator.validate_time_value(None)
    with pytest.raises(BaseAppException, match="必须是字符串"):
        FieldValidator.validate_time_value(1)
    FieldValidator.validate_enum_value(None, {"option": [{"id": "on"}]})
