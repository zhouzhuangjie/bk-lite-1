"""MySQL 监控工具：mock 连接与 SHOW GLOBAL STATUS，断言 QPS/TPS。"""
import json
from unittest.mock import patch

import pytest

from apps.opspilot.metis.llm.tools.mysql import monitoring as mon

pytestmark = pytest.mark.unit

NORMALIZED = {
    "mode": "single",
    "legacy_single": True,
    "items": [{"index": 0, "name": "db1", "raw": {}, "config": {}}],
}


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        return None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        return None


class FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.closed = False

    def cursor(self):
        return FakeCursor(self._rows)

    def close(self):
        self.closed = True


def test_get_database_metrics_computes_qps_tps():
    rows = [
        ("Questions", "100"),
        ("Com_select", "80"),
        ("Com_insert", "10"),
        ("Com_update", "5"),
        ("Com_delete", "5"),
        ("Threads_connected", "3"),
        ("Threads_running", "1"),
        ("Uptime", "10"),
        ("Bytes_received", "2048"),
        ("Bytes_sent", "4096"),
        ("Slow_queries", "2"),
    ]
    conn = FakeConn(rows)
    with (
        patch.object(mon, "build_mysql_normalized_from_runnable", return_value=NORMALIZED),
        patch.object(mon, "get_mysql_connection_from_item", return_value=conn),
    ):
        out = json.loads(mon.get_database_metrics.invoke({"config": {"configurable": {}}}))
    assert out["QPS"] == 10.0
    assert out["TPS"] == 2.0
    assert out["Bytes_received_formatted"] == "2.00 KB"
    assert out["Bytes_sent_formatted"] == "4.00 KB"
    assert conn.closed is True


def test_get_table_metrics_formats_fragmentation():
    rows = [
        {
            "TABLE_NAME": "hosts",
            "ENGINE": "InnoDB",
            "TABLE_ROWS": 100,
            "DATA_LENGTH": 1024,
            "INDEX_LENGTH": 512,
            "DATA_FREE": 256,
            "AUTO_INCREMENT": 10,
            "CREATE_TIME": None,
            "UPDATE_TIME": None,
        }
    ]
    conn = FakeConn([])
    with (
        patch.object(mon, "build_mysql_normalized_from_runnable", return_value={**NORMALIZED, "items": [{**NORMALIZED["items"][0], "config": {"database": "app"}}]}),
        patch.object(mon, "get_mysql_connection_from_item", return_value=conn),
        patch.object(mon, "execute_readonly_query", return_value=rows),
    ):
        out = json.loads(mon.get_table_metrics.invoke({"config": {"configurable": {}}}))
    assert out["database"] == "app"
    assert out["table_count"] == 1
    assert out["tables"][0]["table_name"] == "hosts"
    assert out["tables"][0]["fragmentation_ratio"].endswith("%")
    assert conn.closed is True


def test_get_innodb_stats_hit_ratio():
    rows = [
        ("Innodb_buffer_pool_pages_total", "100"),
        ("Innodb_buffer_pool_pages_data", "80"),
        ("Innodb_buffer_pool_pages_free", "20"),
        ("Innodb_buffer_pool_pages_dirty", "5"),
        ("Innodb_buffer_pool_read_requests", "90"),
        ("Innodb_buffer_pool_reads", "10"),
        ("Innodb_rows_read", "1"),
        ("Innodb_rows_inserted", "1"),
        ("Innodb_rows_updated", "1"),
        ("Innodb_rows_deleted", "1"),
        ("Innodb_row_lock_waits", "0"),
        ("Innodb_row_lock_time", "0"),
    ]
    conn = FakeConn(rows)
    with (
        patch.object(mon, "build_mysql_normalized_from_runnable", return_value=NORMALIZED),
        patch.object(mon, "get_mysql_connection_from_item", return_value=conn),
    ):
        out = json.loads(mon.get_innodb_stats.invoke({"config": {"configurable": {}}}))
    assert out["buffer_pool_hit_ratio"].endswith("%")
    assert out["buffer_pool_usage"].endswith("%")
    assert conn.closed is True


def test_get_io_stats_formats_bytes():
    rows = [
        {
            "FILE_NAME": "/var/lib/mysql/ibdata1",
            "COUNT_READ": 10,
            "COUNT_WRITE": 4,
            "SUM_NUMBER_OF_BYTES_READ": 2048,
            "SUM_NUMBER_OF_BYTES_WRITE": 1024,
            "read_latency_ms": 12,
            "write_latency_ms": 8,
        }
    ]
    conn = FakeConn([])
    with (
        patch.object(mon, "build_mysql_normalized_from_runnable", return_value=NORMALIZED),
        patch.object(mon, "get_mysql_connection_from_item", return_value=conn),
        patch.object(mon, "execute_readonly_query", return_value=rows),
    ):
        out = json.loads(mon.get_io_stats.invoke({"config": {"configurable": {}}}))
    assert out["io_file_count"] == 1
    assert out["io_stats"][0]["file_name"].endswith("ibdata1")
    assert conn.closed is True
