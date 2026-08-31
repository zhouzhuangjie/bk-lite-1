"""MySQL 兼容补丁：migrate_patch 驱动识别、JSON_CONTAINS lookup、ImportError 降级。"""
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from django.db.models.fields.json import DataContains, JSONField

from apps.core.db_patches import mysql as mysql_patch

pytestmark = pytest.mark.unit


def test_patch_migrate_driver_mysql_other_and_missing_engine():
    cornerstone = types.ModuleType("cw_cornerstone")
    mp = types.ModuleType("cw_cornerstone.migrate_patch")
    mgmt = types.ModuleType("cw_cornerstone.migrate_patch.management")
    mgmt.get_db_driver = lambda using: "orig"

    with patch.dict(
        sys.modules,
        {
            "cw_cornerstone": cornerstone,
            "cw_cornerstone.migrate_patch": mp,
            "cw_cornerstone.migrate_patch.management": mgmt,
        },
    ):
        mysql_patch._patch_migrate_patch_mysql_support()
        conn = MagicMock()
        with patch("django.db.connections", {"default": conn}):
            conn.settings_dict = {"ENGINE": "cw_cornerstone.db.mysql.backend"}
            assert mgmt.get_db_driver("default") == "mysql"
            conn.settings_dict = {"ENGINE": "django.db.backends.postgresql"}
            assert mgmt.get_db_driver("default") == "orig"
        with patch("django.db.connections", {}):
            assert mgmt.get_db_driver("missing") == ""


def test_patch_migrate_skips_when_cornerstone_missing():
    with (
        patch.dict(
            sys.modules,
            {"cw_cornerstone.migrate_patch": None, "cw_cornerstone.migrate_patch.management": None},
        ),
        patch("apps.core.db_patches.mysql.logger") as mock_logger,
    ):
        mysql_patch._patch_migrate_patch_mysql_support()
        mock_logger.warning.assert_called_once_with(
            "cw_cornerstone.migrate_patch not installed, skipping MySQL migrate patch support"
        )
        assert sys.modules.get("cw_cornerstone.migrate_patch.management") is None
        assert not hasattr(sys.modules.get("cw_cornerstone.migrate_patch"), "get_db_driver")


def test_json_contains_lookup_uses_mysql_json_contains_then_restores_postgres():
    original = JSONField.class_lookups["contains"]
    try:
        mysql_patch._patch_jsonfield_contains_lookup()
        lookup_cls = JSONField.class_lookups["contains"]
        lookup = object.__new__(lookup_cls)
        lookup.rhs = {"team": 1}
        lookup.process_lhs = lambda compiler, connection: ("col", [])
        sql, params = lookup.as_sql(MagicMock(), MagicMock())
        assert sql == "JSON_CONTAINS(col, %s)"
        assert params == ['{"team": 1}']

        lookup.rhs = '{"a": 1}'
        sql, params = lookup.as_sql(MagicMock(), MagicMock())
        assert params == ['{"a": 1}']

        lookup.rhs = "not-json"
        sql, params = lookup.as_sql(MagicMock(), MagicMock())
        assert params == ['"not-json"']
    finally:
        JSONField.register_lookup(DataContains if original is DataContains else original)
        if JSONField.class_lookups["contains"] is not DataContains:
            JSONField.register_lookup(DataContains)


def test_patch_applies_both_helpers():
    with (
        patch.object(mysql_patch, "_patch_migrate_patch_mysql_support") as migrate,
        patch.object(mysql_patch, "_patch_jsonfield_contains_lookup") as json_lookup,
    ):
        mysql_patch.patch()
    migrate.assert_called_once()
    json_lookup.assert_called_once()
