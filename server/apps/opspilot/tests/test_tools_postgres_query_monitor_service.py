"""PostgreSQL 工具：mock execute_readonly_query，断言热表/未用索引/命中率/慢查询提示。"""
import json
from unittest.mock import patch

import pytest

from apps.opspilot.metis.llm.tools.postgres import analysis as analysis_mod
from apps.opspilot.metis.llm.tools.postgres import monitoring as mon
from apps.opspilot.metis.llm.tools.postgres import query as query_mod
from apps.opspilot.metis.llm.tools.postgres import tracing as tracing_mod
from apps.opspilot.metis.llm.tools.postgres import utils as pg_utils

pytestmark = pytest.mark.unit
CONFIG = {"configurable": {"host": "127.0.0.1", "port": 5432, "database": "app", "user": "u", "password": "p"}}


def _patch(module, rows):
    return patch.object(module, "execute_readonly_query", return_value=rows)


def test_prepare_context_and_formatters():
    assert pg_utils.prepare_context(None)["host"] == "localhost"
    ctx = pg_utils.prepare_context(CONFIG)
    assert ctx["database"] == "app"
    assert pg_utils.format_size(None) == "0 B"
    assert "KB" in pg_utils.format_size(2048)
    assert pg_utils.format_duration(None) == "0ms"
    assert pg_utils.format_duration(12).endswith("ms")
    assert pg_utils.format_duration(2500).endswith("s")
    assert pg_utils.calculate_percentage(1, 0) == 0
    assert pg_utils.calculate_percentage(1, 4) == 25.0


def test_query_table_stats_marks_hot_table_and_filter_path():
    rows = [
        {
            "sequential_scans": 20000,
            "index_scans": 100,
            "n_live_tup": 1,
        }
    ]
    with _patch(query_mod, rows):
        out = json.loads(query_mod.query_table_stats.invoke({"config": CONFIG}))
    assert out["total_tables"] == 1
    assert out["tables"][0]["is_hot_table"] is True
    assert out["tables"][0]["index_scan_ratio"] > 0
    with _patch(query_mod, []):
        filtered = json.loads(query_mod.query_table_stats.invoke({"schema_name": "public", "table_filter": "t%", "config": CONFIG}))
    assert filtered["total_tables"] == 0
    with patch.object(query_mod, "execute_readonly_query", side_effect=RuntimeError("denied")):
        err = json.loads(query_mod.query_table_stats.invoke({"config": CONFIG}))
    assert "denied" in err["error"]


def test_query_index_usage_flags_unused():
    rows = [
        {"index_scans": 0, "tuples_read": 0, "tuples_fetched": 0, "index_size_bytes": 1024, "index_name": "idx_dead"},
        {"index_scans": 10, "tuples_read": 100, "tuples_fetched": 80, "index_size_bytes": 2048, "index_name": "idx_hot"},
    ]
    with _patch(query_mod, rows):
        out = json.loads(query_mod.query_index_usage.invoke({"table": "hosts", "config": CONFIG}))
    unused = [r for r in out["indexes"] if r["is_unused"]]
    assert len(unused) == 1
    assert unused[0]["index_name"] == "idx_dead"
    assert "index_size" in out["indexes"][0]


def test_database_metrics_computes_rollback_ratio():
    rows = [
        {
            "database": "app",
            "temporary_bytes": 2048,
            "stats_reset": None,
            "transactions_committed": 90,
            "transactions_rolled_back": 10,
        }
    ]
    with _patch(mon, rows):
        out = json.loads(mon.get_database_metrics.invoke({"config": CONFIG}))
    assert out["total_databases"] == 1
    db = out["databases"][0]
    assert db["rollback_ratio"] == 10.0
    assert db["temporary_size"].endswith("KB") or "B" in db["temporary_size"]
    assert db["stats_reset"] == "Never"


def test_cache_hit_ratio_performance_bands():
    poor = [{"database": "a", "blocks_hit": 10, "blocks_read": 90}]
    with _patch(analysis_mod, poor):
        out = json.loads(analysis_mod.analyze_cache_hit_ratio.invoke({"config": CONFIG}))
    assert out["performance"] == "poor"
    assert out["overall_cache_hit_ratio"] == 10.0
    excellent = [{"database": "a", "blocks_hit": 999, "blocks_read": 1}]
    with _patch(analysis_mod, excellent):
        out = json.loads(analysis_mod.analyze_cache_hit_ratio.invoke({"config": CONFIG}))
    assert out["performance"] == "excellent"


def test_top_queries_formats_duration_and_missing_extension():
    rows = [
        {
            "query": "SELECT 1",
            "total_time": 1500,
            "mean_time": 15,
            "min_time": 1,
            "max_time": 40,
        }
    ]
    with _patch(tracing_mod, rows):
        out = json.loads(tracing_mod.get_top_queries.invoke({"order_by": "calls", "config": CONFIG}))
    assert out["total_queries"] == 1
    assert "ms" in out["queries"][0]["mean_time_formatted"] or "s" in out["queries"][0]["mean_time_formatted"]
    with patch.object(tracing_mod, "execute_readonly_query", side_effect=RuntimeError("relation pg_stat_statements does not exist")):
        err = json.loads(tracing_mod.get_top_queries.invoke({"config": CONFIG}))
    assert "pg_stat_statements" in err["error"]
    assert "suggestion" in err
