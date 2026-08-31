"""CMDB 字段校验剩余契约：公共枚举库、组织/用户/时间、批量校验异常收集。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.cmdb.validators.field_validator import FieldValidator
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.unit


def test_validate_enum_public_library_and_fallback():
    library = MagicMock()
    library.options = [{"id": "on"}, {"id": "off"}]
    attr = {
        "enum_rule_type": "public_library",
        "public_library_id": 7,
        "option": [{"id": "fallback"}],
    }
    with patch(
        "apps.cmdb.services.public_enum_library.get_library_or_raise",
        return_value=library,
    ):
        FieldValidator.validate_enum_value("on", attr)
        with pytest.raises(BaseAppException, match="不在有效选项范围内"):
            FieldValidator.validate_enum_value("nope", attr)
        with pytest.raises(BaseAppException, match="不在有效选项范围内"):
            FieldValidator.validate_enum_value(["on", "bad"], attr)

    with patch(
        "apps.cmdb.services.public_enum_library.get_library_or_raise",
        side_effect=RuntimeError("missing"),
    ):
        FieldValidator.validate_enum_value("fallback", attr)

    no_lib = {"enum_rule_type": "public_library", "option": [{"id": "x"}]}
    FieldValidator.validate_enum_value("x", no_lib)


def test_validate_field_by_attr_org_user_time_and_empty_attr():
    FieldValidator.validate_field_by_attr("x", {})
    FieldValidator.validate_organization_value([], "org")
    FieldValidator.validate_field_by_attr([1, 2], {"attr_id": "org", "attr_type": "organization"})
    with pytest.raises(BaseAppException, match="必须是数组"):
        FieldValidator.validate_field_by_attr("team", {"attr_id": "org", "attr_type": "organization"})
    FieldValidator.validate_field_by_attr([3], {"attr_id": "owner", "attr_type": "user"})
    with pytest.raises(BaseAppException, match="必须是整数"):
        FieldValidator.validate_field_by_attr(["u1"], {"attr_id": "owner", "attr_type": "user"})
    FieldValidator.validate_field_by_attr("2025-01-02T03:04:05+00:00", {"attr_id": "ts", "attr_type": "time"})
    with pytest.raises(BaseAppException, match="必须是字符串"):
        FieldValidator.validate_field_by_attr(123, {"attr_id": "ts", "attr_type": "time"})


def test_validate_instance_data_collects_unexpected_exceptions(monkeypatch):
    attrs = [{"attr_id": "ip", "attr_name": "IP", "attr_type": "str", "option": {"validation_type": "ipv4"}}]
    monkeypatch.setattr(
        FieldValidator,
        "validate_field_by_attr",
        staticmethod(lambda value, attr: (_ for _ in ()).throw(RuntimeError("boom"))),
    )
    errors = FieldValidator.validate_instance_data({"ip": "10.0.0.1"}, attrs)
    assert len(errors) == 1
    assert errors[0]["field"] == "ip"
    assert "boom" in errors[0]["error"]
