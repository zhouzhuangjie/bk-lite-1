"""唯一规则复制到目标模型、字段变更守卫。"""
from unittest.mock import patch

import pytest

from apps.cmdb.services import unique_rule as ur
from apps.cmdb.services.unique_rule import ModelUniqueRule, UniqueRuleCheckContext, UniqueRulePayload
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.unit


def test_copy_unique_rules_empty_source_clears_destination():
    empty = UniqueRuleCheckContext(model_id="src", attrs_by_id={}, unique_rules=[])
    with patch.object(ur, "build_unique_rule_context", return_value=empty), patch.object(ur, "_save_unique_rules") as save:
        assert ur.copy_unique_rules_to_model("src", "dst", "admin") == []
    save.assert_called_once_with("dst", [])


def test_copy_unique_rules_validates_and_persists_new_ids():
    src = UniqueRuleCheckContext(
        model_id="src",
        attrs_by_id={"ip": {"is_required": True, "attr_type": "str"}},
        unique_rules=[ModelUniqueRule(rule_id="old", order=1, field_ids=["ip"])],
    )
    dst = UniqueRuleCheckContext(
        model_id="dst",
        attrs_by_id={"ip": {"is_required": True, "attr_type": "str"}},
        unique_rules=[],
    )

    def _ctx(model_id):
        return src if model_id == "src" else dst

    with patch.object(ur, "build_unique_rule_context", side_effect=_ctx), patch.object(
        ur, "validate_unique_rule_payload"
    ) as validate, patch.object(ur, "_save_unique_rules") as save:
        copied = ur.copy_unique_rules_to_model("src", "dst", "alice")
    assert len(copied) == 1
    assert copied[0].field_ids == ["ip"]
    assert copied[0].order == 1
    assert copied[0].rule_id != "old"
    validate.assert_called_once()
    payload = validate.call_args.args[1]
    assert isinstance(payload, UniqueRulePayload)
    assert payload.field_ids == ["ip"]
    save.assert_called_once_with("dst", copied)


def test_guard_attr_change_blocks_delete_and_allows_unrelated():
    ctx = UniqueRuleCheckContext(
        model_id="host",
        attrs_by_id={"ip": {"is_required": True, "attr_type": "str"}},
        unique_rules=[ModelUniqueRule(rule_id="r1", order=1, field_ids=["ip"])],
    )
    with patch.object(ur, "build_unique_rule_context", return_value=ctx):
        with pytest.raises(BaseAppException, match="请先删除相关唯一规则"):
            ur.guard_attr_change_against_unique_rules("host", "ip", None, "delete", operator="bob")
        with pytest.raises(BaseAppException, match="不能取消必填"):
            ur.guard_attr_change_against_unique_rules("host", "ip", {"is_required": False}, "update_required")
        with pytest.raises(BaseAppException, match="不能修改为 enum"):
            ur.guard_attr_change_against_unique_rules("host", "ip", {"attr_type": "enum"}, "update_type")
        ur.guard_attr_change_against_unique_rules("host", "ip", {"is_required": True}, "update_required")
        ur.guard_attr_change_against_unique_rules("host", "hostname", None, "delete")
