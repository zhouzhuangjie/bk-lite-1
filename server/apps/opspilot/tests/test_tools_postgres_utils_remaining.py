"""PostgreSQL 工具 utils：连接回退、只读查询、格式化与版本解析契约。"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from apps.opspilot.metis.llm.tools.postgres import utils as pgutils

pytestmark = pytest.mark.unit


def test_prepare_context_defaults_and_object_config():
    assert pgutils.prepare_context(None) == {
        "host": "localhost",
        "port": 5432,
        "database": "postgres",
        "user": "postgres",
        "password": "",
    }
    cfg = SimpleNamespace(configurable={"host": "db.local", "port": 15432, "database": "ops", "user": "u", "password": "p"})
    assert pgutils.prepare_context(cfg)["host"] == "db.local"
    assert pgutils.prepare_context(cfg)["port"] == 15432


def test_get_db_connection_legacy_overrides_database_and_reraises():
    captured = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    with patch.object(pgutils.psycopg2, "connect", side_effect=fake_connect):
        conn = pgutils.get_db_connection({"configurable": {"host": "h", "user": "u"}}, database="ops")
    assert conn is not None
    assert captured["database"] == "ops"
    assert captured["host"] == "h"
    assert captured["connect_timeout"] == 10

    with patch.object(pgutils.psycopg2, "connect", side_effect=psycopg2.OperationalError("down")):
        with pytest.raises(psycopg2.Error):
            pgutils.get_db_connection({"configurable": {"host": "h"}})


def test_get_db_connection_multi_instance_reconnects_when_database_overridden():
    first = MagicMock()
    second = MagicMock()
    item = {"config": {"host": "h", "port": 5432, "database": "postgres", "user": "u", "password": "p"}}
    normalized = SimpleNamespace(items=[item])

    with (
        patch(
            "apps.opspilot.metis.llm.tools.postgres.connection.build_postgres_normalized_from_runnable",
            return_value=normalized,
        ),
        patch(
            "apps.opspilot.metis.llm.tools.postgres.connection.get_postgres_connection_from_item",
            return_value=first,
        ) as from_item,
        patch.object(pgutils.psycopg2, "connect", return_value=second) as connect,
    ):
        out = pgutils.get_db_connection(
            {"configurable": {"postgres_instances": [{"host": "h"}]}},
            database="ops",
        )
    from_item.assert_called_once_with(item)
    first.close.assert_called_once()
    assert connect.call_args.kwargs["database"] == "ops"
    assert out is second


def test_execute_readonly_query_commits_and_rolls_back():
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"id": 1}]
    conn = MagicMock()
    conn.cursor.return_value = cursor

    with patch.object(pgutils, "get_db_connection", return_value=conn):
        rows = pgutils.execute_readonly_query("SELECT 1", params=(1,), config={})
    assert rows == [{"id": 1}]
    cursor.execute.assert_any_call("BEGIN TRANSACTION READ ONLY")
    cursor.execute.assert_any_call("SELECT 1", (1,))
    conn.commit.assert_called_once()
    cursor.close.assert_called_once()
    conn.close.assert_called_once()

    cursor.execute.side_effect = [None, psycopg2.ProgrammingError("bad sql")]
    with patch.object(pgutils, "get_db_connection", return_value=conn):
        with pytest.raises(psycopg2.Error):
            pgutils._execute_readonly_query_blocking("SELECT boom")
    conn.rollback.assert_called()


def test_format_size_duration_percentage_and_json():
    assert pgutils.format_size(None) == "0 B"
    assert pgutils.format_size(512) == "512.00 B"
    assert pgutils.format_size(1024) == "1.00 KB"
    assert pgutils.format_size(1024**5) == "1.00 PB"
    assert pgutils.format_duration(None) == "0ms"
    assert pgutils.format_duration(0.5) == "500.00μs"
    assert pgutils.format_duration(20) == "20.00ms"
    assert pgutils.format_duration(2500) == "2.50s"
    assert pgutils.format_duration(120000) == "2.00min"
    assert pgutils.format_duration(7200000) == "2.00h"
    assert pgutils.calculate_percentage(1, 0) == 0.0
    assert pgutils.calculate_percentage(1, 4) == 25.0
    dumped = pgutils.safe_json_dumps({"ts": datetime(2026, 1, 2, 3, 4, 5), "obj": object()})
    assert "2026-01-02T03:04:05" in dumped
    assert "obj" in dumped


def test_parse_pg_version_extracts_major_and_falls_back():
    with patch.object(pgutils, "execute_readonly_query", return_value=[{"version": "PostgreSQL 14.5 on x86_64"}]):
        info = pgutils.parse_pg_version({})
    assert info == {"full_version": "PostgreSQL 14.5 on x86_64", "version_number": "14.5", "major_version": 14}

    with patch.object(pgutils, "execute_readonly_query", side_effect=RuntimeError("down")):
        assert pgutils.parse_pg_version({}) == {
            "full_version": "unknown",
            "version_number": "unknown",
            "major_version": 0,
        }
