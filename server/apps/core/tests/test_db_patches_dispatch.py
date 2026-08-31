"""数据库补丁入口分发，以及 OceanBase / GoldenDB / GaussDB 常规补丁契约。"""
import logging
from unittest.mock import MagicMock, patch

import pytest
from django.db.models.fields.json import DataContains, JSONField

from apps.core.db_patches import apply_patches, gaussdb, goldendb, oceanbase

pytestmark = pytest.mark.unit


def test_apply_patches_skips_unknown_engine(monkeypatch, caplog):
    monkeypatch.setattr(
        "apps.core.db_patches.settings.DATABASES",
        {"default": {"ENGINE": "django.db.backends.postgresql"}},
    )
    with caplog.at_level(logging.DEBUG, logger="apps.core.db_patches"):
        apply_patches()
    assert "No database patches needed for engine: django.db.backends.postgresql" in caplog.text


def test_apply_patches_dispatches_to_matching_engine(monkeypatch):
    monkeypatch.setattr(
        "apps.core.db_patches.settings.DATABASES",
        {"default": {"ENGINE": "vendor.oceanbase.backend"}},
    )
    fake = MagicMock()
    with patch("importlib.import_module", return_value=fake) as importer:
        apply_patches()
    importer.assert_called_once_with("apps.core.db_patches.oceanbase")
    fake.patch.assert_called_once_with()


def test_apply_patches_logs_and_swallows_patch_failure(monkeypatch, caplog):
    monkeypatch.setattr(
        "apps.core.db_patches.settings.DATABASES",
        {"default": {"ENGINE": "django.db.backends.mysql"}},
    )
    fake = MagicMock()
    fake.patch.side_effect = RuntimeError("boom")
    with caplog.at_level(logging.ERROR, logger="apps.core.db_patches"):
        with patch("importlib.import_module", return_value=fake):
            apply_patches()
    assert "Failed to apply database patches for engine: mysql" in caplog.text


def _restore_json_contains(original):
    JSONField.register_lookup(DataContains if original is DataContains else original)
    if JSONField.class_lookups["contains"] is not DataContains:
        JSONField.register_lookup(DataContains)


def _assert_json_contains_lookup(patch_fn):
    original = JSONField.class_lookups["contains"]
    try:
        patch_fn()
        lookup_cls = JSONField.class_lookups["contains"]
        lookup = object.__new__(lookup_cls)
        lookup.rhs = {"team": 1}
        lookup.process_lhs = lambda compiler, connection: ("col", [])
        sql, params = lookup.as_sql(MagicMock(), MagicMock())
        assert sql == "JSON_CONTAINS(col, %s)"
        assert params == ['{"team": 1}']

        lookup.rhs = '{"a": 1}'
        _, params = lookup.as_sql(MagicMock(), MagicMock())
        assert params == ['{"a": 1}']

        lookup.rhs = "not-json"
        _, params = lookup.as_sql(MagicMock(), MagicMock())
        assert params == ['"not-json"']
    finally:
        _restore_json_contains(original)


def test_oceanbase_json_contains_lookup_and_patch_wrapper():
    _assert_json_contains_lookup(oceanbase._patch_jsonfield_contains_lookup)
    with patch.object(oceanbase, "_patch_jsonfield_contains_lookup") as inner:
        oceanbase.patch()
    inner.assert_called_once_with()


def test_goldendb_json_contains_lookup_and_patch_wrapper():
    _assert_json_contains_lookup(goldendb._patch_jsonfield_contains_lookup)
    with patch.object(goldendb, "_patch_jsonfield_contains_lookup") as inner:
        goldendb.patch()
    inner.assert_called_once_with()


def test_gaussdb_patch_only_logs(caplog):
    with caplog.at_level(logging.INFO, logger="apps.core.db_patches.gaussdb"):
        gaussdb.patch()
    assert "GaussDB ORM patches applied" in caplog.text
