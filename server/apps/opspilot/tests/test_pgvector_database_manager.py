"""pgvector DatabaseManager / ConnectionPool：URI 转换、查询/更新、连接复用与失效。"""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psycopg
import pytest

from apps.opspilot.metis.llm.rag.naive_rag.pgvector.database_connection_pool import DatabaseConnectionPool
from apps.opspilot.metis.llm.rag.naive_rag.pgvector.database_manager import DatabaseManager

pytestmark = pytest.mark.unit


class _Cursor:
    def __init__(self, description=None, rows=None, rowcount=1):
        self.description = description
        self._rows = rows or []
        self.rowcount = rowcount

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_convert_uri_strips_psycopg_dialect():
    mgr = DatabaseManager("postgresql+psycopg://u:p@h/db")
    assert mgr.db_uri == "postgresql://u:p@h/db"
    mgr2 = DatabaseManager("postgres+psycopg://u:p@h/db")
    assert mgr2.db_uri == "postgresql://u:p@h/db"
    mgr3 = DatabaseManager("postgresql://u:p@h/db")
    assert mgr3.db_uri == "postgresql://u:p@h/db"


def test_execute_query_maps_rows_and_wraps_errors():
    mgr = DatabaseManager("postgresql://u:p@h/db")
    cur = _Cursor(description=[("id",), ("name",)], rows=[(1, "a")])
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.commit = MagicMock()

    @contextmanager
    def fake_conn():
        yield conn

    mgr._pool.get_connection = fake_conn
    assert mgr.execute_query("select 1", {"id": 1}) == [{"id": 1, "name": "a"}]

    cur2 = _Cursor(description=None, rows=[])
    conn.cursor.return_value = cur2
    assert mgr.execute_query("update t set x=1") == []

    def boom_conn(exc):
        @contextmanager
        def _cm():
            raise exc
            yield  # pragma: no cover

        return _cm

    mgr._pool.get_connection = boom_conn(psycopg.OperationalError("refused"))
    with pytest.raises(RuntimeError, match="数据库连接失败: refused"):
        mgr.execute_query("select 1")
    mgr._pool.get_connection = boom_conn(psycopg.Error("syntax"))
    with pytest.raises(RuntimeError, match="数据库查询操作失败: syntax"):
        mgr.execute_query("select 1")
    mgr._pool.get_connection = boom_conn(RuntimeError("other"))
    with pytest.raises(RuntimeError, match="数据库查询操作失败: other"):
        mgr.execute_query("select 1")


def test_execute_update_returns_rowcount_and_wraps_errors():
    mgr = DatabaseManager("postgresql://u:p@h/db")
    cur = _Cursor(rowcount=3)
    conn = MagicMock()
    conn.cursor.return_value = cur

    @contextmanager
    def fake_conn():
        yield conn

    mgr._pool.get_connection = fake_conn
    assert mgr.execute_update("delete from t", {"id": 1}) == 3

    def boom_conn(exc):
        @contextmanager
        def _cm():
            raise exc
            yield  # pragma: no cover

        return _cm

    mgr._pool.get_connection = boom_conn(psycopg.OperationalError("down"))
    with pytest.raises(RuntimeError, match="数据库连接失败: down"):
        mgr.execute_update("delete from t")
    mgr._pool.get_connection = boom_conn(psycopg.Error("fk"))
    with pytest.raises(RuntimeError, match="数据库更新操作失败: fk"):
        mgr.execute_update("delete from t")
    mgr._pool.get_connection = boom_conn(ValueError("bad"))
    with pytest.raises(RuntimeError, match="数据库更新操作失败: bad"):
        mgr.execute_update("delete from t")


def test_connection_pool_reuses_valid_conn_and_drops_dead():
    pool = DatabaseConnectionPool("postgresql://u:p@h/db", max_connections=2)
    live = MagicMock()
    live.closed = False
    live.execute.return_value = 1
    dead = MagicMock()
    dead.closed = False
    dead.execute.side_effect = psycopg.OperationalError("gone")
    dead.close.side_effect = RuntimeError("already closed")
    pool._connections = [live, dead]
    pool._created_count = 2
    conn = pool._acquire_connection()
    assert conn is live
    assert pool._created_count == 1

    created = MagicMock()
    created.closed = False
    with patch("apps.opspilot.metis.llm.rag.naive_rag.pgvector.database_connection_pool.psycopg.connect", return_value=created):
        assert pool._acquire_connection() is created
        assert pool._created_count == 2
    with pytest.raises(RuntimeError, match="连接池已满，无法创建新连接"):
        pool._acquire_connection()

    with patch(
        "apps.opspilot.metis.llm.rag.naive_rag.pgvector.database_connection_pool.psycopg.connect",
        side_effect=RuntimeError("auth"),
    ):
        pool._created_count = 0
        with pytest.raises(RuntimeError, match="auth"):
            pool._acquire_connection()


def test_connection_pool_release_and_context_manager():
    pool = DatabaseConnectionPool("postgresql://u:p@h/db", max_connections=1)
    conn = MagicMock()
    conn.closed = False
    pool._created_count = 1
    pool._release_connection(conn)
    assert pool._connections == [conn]

    extra = MagicMock()
    extra.closed = False
    extra.close.side_effect = RuntimeError("close fail")
    pool._created_count = 1
    pool._release_connection(extra)
    extra.close.assert_called_once()
    assert pool._created_count == 0

    closed = MagicMock()
    closed.closed = True
    pool._created_count = 1
    pool._connections = []
    pool._release_connection(closed)
    closed.close.assert_called_once()

    acquired = MagicMock()
    with patch.object(pool, "_acquire_connection", return_value=acquired), patch.object(pool, "_release_connection") as release:
        with pool.get_connection() as c:
            assert c is acquired
        release.assert_called_once_with(acquired)
