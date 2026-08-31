"""PrecheckService._format_pydantic_error：把校验错误转成可读中文。"""
import pytest

from apps.operation_analysis.services.import_export.precheck_service import PrecheckService

pytestmark = pytest.mark.unit


class _FakeError(Exception):
    def __init__(self, errors):
        self._errors = errors

    def errors(self):
        return self._errors


def test_format_pydantic_error_maps_common_types_and_limits_to_three():
    fake = _FakeError(
        [
            {"loc": ("dashboards", 0, "name"), "msg": "str expected", "type": "string_type"},
            {"loc": ("datasources",), "msg": "list expected", "type": "list_type"},
            {"loc": ("meta",), "msg": "dict expected", "type": "dict_type"},
            {"loc": ("count",), "msg": "int expected", "type": "int_type"},
            {"loc": ("enabled",), "msg": "bool expected", "type": "bool_type"},
        ]
    )
    text = PrecheckService._format_pydantic_error(fake)
    assert "应为字符串类型" in text
    assert "应为列表(list)类型" in text
    assert "应为对象(dict)类型" in text
    assert text.count(";") == 2  # 最多 3 条


def test_format_pydantic_error_missing_and_value_error():
    fake = _FakeError(
        [
            {"loc": ("id",), "msg": "Field required", "type": "missing"},
            {"loc": ("type",), "msg": "not allowed", "type": "value_error.const"},
            {"loc": ("x",), "msg": "nope", "type": "other_error"},
        ]
    )
    text = PrecheckService._format_pydantic_error(fake)
    assert "缺少必填字段" in text
    assert "值无效" in text
    assert "校验失败" in text
