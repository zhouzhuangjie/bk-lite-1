"""cmdb_migrate_scalar_to_list：dry-run 不写库，实跑把标量字段包成 list。"""
import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from apps.cmdb.constants.constants import INSTANCE, MODEL

pytestmark = pytest.mark.unit


def _client(models, instances, setter=None):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False

    def query_entity(kind, filters):
        if kind == MODEL:
            return models, len(models)
        return instances, len(instances)

    client.query_entity.side_effect = query_entity
    if setter is not None:
        client.set_entity_properties.side_effect = setter
    return client


def test_dry_run_migrates_scalar_without_writing():
    models = [
        {
            "model_id": "host",
            "attrs": json.dumps(
                [
                    {"attr_id": "owners", "attr_type": "user"},
                    {"attr_id": "tags", "attr_type": "string"},
                ]
            ),
        }
    ]
    instances = [
        {"_id": 11, "inst_name": "h1", "owners": "alice", "tags": "x"},
        {"_id": 12, "inst_name": "h2", "owners": ["bob"]},
        {"_id": 13, "inst_name": "h3"},
    ]
    client = _client(models, instances)
    stdout = StringIO()
    with patch(
        "apps.cmdb.management.commands.cmdb_migrate_scalar_to_list.GraphClient",
        return_value=client,
    ):
        call_command("cmdb_migrate_scalar_to_list", dry_run=True, stdout=stdout)
    client.set_entity_properties.assert_not_called()
    out = stdout.getvalue()
    assert "dry-run" in out
    assert "owners" in out
    assert "需迁移 1 个实例" in out


def test_write_mode_updates_scalar_and_skips_missing_model():
    models = [
        {
            "model_id": "host",
            "attrs": json.dumps([{"attr_id": "owners", "attr_type": "organization"}]),
        },
        {"model_id": "bad", "attrs": "{not-json"},
    ]
    instances = [{"_id": 21, "inst_name": "n1", "owners": "ops"}]
    client = _client(models, instances)
    stdout = StringIO()
    with patch(
        "apps.cmdb.management.commands.cmdb_migrate_scalar_to_list.GraphClient",
        return_value=client,
    ):
        call_command("cmdb_migrate_scalar_to_list", stdout=stdout)
    client.set_entity_properties.assert_called_once_with(
        INSTANCE, [21], {"owners": ["ops"]}, {}, [], False
    )
    assert "attrs 解析失败" in stdout.getvalue()

    empty_client = _client([], [])
    empty_out = StringIO()
    with patch(
        "apps.cmdb.management.commands.cmdb_migrate_scalar_to_list.GraphClient",
        return_value=empty_client,
    ):
        call_command("cmdb_migrate_scalar_to_list", model="ghost", stdout=empty_out)
    empty_client.set_entity_properties.assert_not_called()
    assert "未找到模型: ghost" in empty_out.getvalue()
