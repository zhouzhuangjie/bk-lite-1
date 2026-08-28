"""ModelManage 唯一性规则：create/update/delete 转调 unique_rule 服务并回读。"""
from unittest.mock import patch

import pytest

from apps.cmdb.services.model import ModelManage
from apps.cmdb.services.unique_rule import UniqueRulePayload

pytestmark = pytest.mark.unit


def test_create_update_delete_unique_rule_delegate_and_return_listing():
    listing = {"rules": [{"id": "r1", "field_ids": ["ip"]}]}
    with (
        patch("apps.cmdb.services.model.create_unique_rule") as create,
        patch("apps.cmdb.services.model.update_unique_rule") as update,
        patch("apps.cmdb.services.model.delete_unique_rule") as delete,
        patch.object(ModelManage, "get_model_unique_rules", return_value=listing),
    ):
        created = ModelManage.create_model_unique_rule("host", {"field_ids": ["ip"]}, username="alice")
        updated = ModelManage.update_model_unique_rule("host", "r1", {"field_ids": ["ip", "name"]}, username="bob")
        deleted = ModelManage.delete_model_unique_rule("host", "r1", username="carol")

    assert created == listing
    assert updated == listing
    assert deleted == listing
    create.assert_called_once()
    payload = create.call_args.args[1]
    assert isinstance(payload, UniqueRulePayload)
    assert payload.field_ids == ["ip"]
    assert create.call_args.args[2] == "alice"
    update.assert_called_once()
    assert update.call_args.args[1] == "r1"
    assert update.call_args.args[2].field_ids == ["ip", "name"]
    delete.assert_called_once_with("host", "r1", "carol")
