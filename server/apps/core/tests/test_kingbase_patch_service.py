"""KingbaseES MySQL 兼容补丁：幂等、pattern_ops concat 改写、introspection SQL 使用 concat。"""
import pytest
from django.db.backends.postgresql.base import DatabaseWrapper
from django.db.backends.postgresql.introspection import DatabaseIntrospection

from apps.core.db_patches import kingbase

pytestmark = pytest.mark.unit


def test_apply_early_patches_is_idempotent(monkeypatch):
    original_ops = dict(DatabaseWrapper.pattern_ops)
    monkeypatch.setattr(kingbase, "_patches_applied", True)
    kingbase.apply_early_patches()
    assert DatabaseWrapper.pattern_ops == original_ops


def test_pattern_ops_rewrites_pipe_concat_to_concat():
    original = dict(DatabaseWrapper.pattern_ops)
    try:
        kingbase._patch_pattern_ops_pipe_concat()
        ops = DatabaseWrapper.pattern_ops
        assert "||" not in ops["contains"]
        assert ops["contains"] == "LIKE concat('%%', {}, '%%')"
        assert ops["startswith"] == "LIKE concat({}, '%%')"
        assert ops["iendswith"] == "LIKE concat('%%', UPPER({}))"
    finally:
        DatabaseWrapper.pattern_ops = original


def test_introspection_get_constraints_sql_uses_concat_not_pipe():
    original = DatabaseIntrospection.get_constraints
    try:
        kingbase._patch_introspection_pipe_concat()
        executed = []

        class _Cursor:
            def execute(self, sql, params=None):
                executed.append(sql)

            def fetchall(self):
                return []

        class _Self:
            index_default_access_method = "btree"

        DatabaseIntrospection.get_constraints(_Self(), _Cursor(), "demo_table")
        joined = "\n".join(executed)
        assert "concat(fkc.relname, '.', fka.attname)" in joined
        assert "fkc.relname || '.' || fka.attname" not in joined
    finally:
        DatabaseIntrospection.get_constraints = original


def test_psycopg3_timestamptz_patch_retries_naive_timestamp():
    pytest.importorskip("psycopg")
    from psycopg.errors import DataError
    from psycopg.types.datetime import TimestamptzLoader

    original = TimestamptzLoader.load
    seen = []

    def exploding_load(self, data):
        seen.append(data)
        if data == b"2026-06-23 09:59:57":
            raise DataError("can't parse timestamp")
        return "parsed"

    TimestamptzLoader.load = exploding_load
    try:
        kingbase._patch_psycopg3_timestamptz_missing_tz()
        loader = object.__new__(TimestamptzLoader)
        assert TimestamptzLoader.load(loader, b"2026-06-23 09:59:57") == "parsed"
        assert seen == [b"2026-06-23 09:59:57", b"2026-06-23 09:59:57+00"]
    finally:
        TimestamptzLoader.load = original
