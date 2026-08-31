"""MSSQL 工具函数单元测试。

MSSQL utils 在导入时即依赖 pyodbc(进而需要系统 unixodbc 动态库)。在缺少该库的
本机/CI 环境下整文件跳过,而不让收集报错。覆盖标识符引用护栏、格式化、单位字段
富化与 JSON 序列化。
"""

import pytest

# pyodbc 在导入 mssql.utils 时被加载;缺 unixodbc 时整文件跳过。
pytest.importorskip("pyodbc", reason="pyodbc/unixodbc 未安装,跳过 MSSQL 工具测试")

from apps.opspilot.metis.llm.tools.mssql import utils as ms_utils  # noqa: E402


class TestMssqlQuoteIdentifier:
    def test_valid_name(self):
        assert ms_utils.quote_database_identifier("mydb") == "[mydb]"

    def test_underscore_and_digits(self):
        assert ms_utils.quote_database_identifier("db_1") == "[db_1]"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            ms_utils.quote_database_identifier("")

    def test_injection_bracket_raises(self):
        with pytest.raises(ValueError):
            ms_utils.quote_database_identifier("db];DROP")

    def test_space_raises(self):
        with pytest.raises(ValueError):
            ms_utils.quote_database_identifier("my db")


class TestMssqlPrepareContext:
    def test_defaults(self):
        out = ms_utils.prepare_context(None)
        assert out == {"host": "localhost", "port": 1433, "database": "master", "user": "sa", "password": ""}

    def test_from_configurable(self):
        cfg = {"configurable": {"host": "h", "port": 1434, "database": "d", "user": "u", "password": "p"}}
        out = ms_utils.prepare_context(cfg)
        assert out["host"] == "h" and out["port"] == 1434


class TestMssqlFormatters:
    def test_format_size_none(self):
        assert ms_utils.format_size(None) == "0 B"

    def test_format_size_gb(self):
        assert ms_utils.format_size(1024 ** 3) == "1.00 GB"

    def test_format_duration_ms(self):
        assert ms_utils.format_duration(250) == "250.00ms"

    def test_calculate_percentage(self):
        assert ms_utils.calculate_percentage(50, 200) == 25.0
        assert ms_utils.calculate_percentage(1, 0) == 0.0


class TestMssqlEnrichUnitFields:
    def test_size_bytes_gets_display(self):
        out = ms_utils.enrich_unit_fields({"size_bytes": 1024})
        assert out["size_bytes"] == 1024
        assert out["size_bytes_display"] == "1.00 KB"

    def test_percent_field_formatted(self):
        out = ms_utils.enrich_unit_fields({"usage_percent": 12.345})
        assert out["usage_percent_display"] == "12.35%"

    def test_nested_list_recursion(self):
        out = ms_utils.enrich_unit_fields([{"avg_time_ms": 1500}])
        assert out[0]["avg_time_ms_display"] == "1.50s"

    def test_legacy_alias_added(self):
        out = ms_utils.enrich_unit_fields({"size_mb": 1})
        assert "size_formatted" in out

    def test_bool_not_treated_as_numeric(self):
        out = ms_utils.enrich_unit_fields({"usage_percent": True})
        assert "usage_percent_display" not in out

    def test_existing_display_not_overwritten(self):
        out = ms_utils.enrich_unit_fields({"size_bytes": 1024, "size_bytes_display": "custom"})
        assert out["size_bytes_display"] == "custom"


class TestMssqlSafeJsonDumps:
    def test_enriches_and_serializes(self):
        out = ms_utils.safe_json_dumps({"size_bytes": 1024})
        assert '"size_bytes_display": "1.00 KB"' in out

    def test_serializes_datetime_via_default_handler(self):
        from datetime import datetime

        out = ms_utils.safe_json_dumps({"ts": datetime(2026, 1, 2, 3, 4, 5)})
        assert "2026-01-02T03:04:05" in out


class TestMssqlDriverAndConnection:
    def test_get_available_driver_prefers_18(self, monkeypatch):
        monkeypatch.setattr(
            ms_utils.pyodbc,
            "drivers",
            lambda: ["SQL Server", "ODBC Driver 18 for SQL Server"],
            raising=False,
        )
        assert ms_utils.get_available_driver() == "ODBC Driver 18 for SQL Server"

    def test_get_available_driver_raises_when_empty(self, monkeypatch):
        monkeypatch.setattr(ms_utils.pyodbc, "drivers", lambda: ["Other"], raising=False)
        with pytest.raises(RuntimeError, match="未找到可用的SQL Server ODBC驱动"):
            ms_utils.get_available_driver()

    def test_get_available_driver_raises_when_list_fails(self, monkeypatch):
        def boom():
            raise RuntimeError("odbc missing")

        monkeypatch.setattr(ms_utils.pyodbc, "drivers", boom, raising=False)
        with pytest.raises(RuntimeError, match="未找到可用的SQL Server ODBC驱动"):
            ms_utils.get_available_driver()

    def test_get_db_connection_uses_driver_18_and_database_override(self, monkeypatch):
        captured = {}

        def fake_connect(conn_str, timeout=0):
            captured["conn_str"] = conn_str
            captured["timeout"] = timeout
            return "conn"

        monkeypatch.setattr(ms_utils, "get_available_driver", lambda: "ODBC Driver 18 for SQL Server")
        monkeypatch.setattr(ms_utils.pyodbc, "connect", fake_connect)
        conn = ms_utils.get_db_connection({"configurable": {"host": "h", "port": 1433, "database": "master", "user": "u", "password": "p"}}, database="appdb")
        assert conn == "conn"
        assert "DATABASE=appdb" in captured["conn_str"]
        assert "TrustServerCertificate=yes" in captured["conn_str"]
        assert captured["timeout"] == 10

    def test_get_db_connection_instance_id_switches_database(self, monkeypatch):
        class FakeConn:
            def __init__(self):
                self.executed = []

            def execute(self, sql):
                self.executed.append(sql)

        fake = FakeConn()
        monkeypatch.setattr(
            "apps.opspilot.metis.llm.tools.mssql.connection.get_mssql_connection",
            lambda config, instance_name=None, instance_id=None: fake,
        )
        conn = ms_utils.get_db_connection({}, database="sales", instance_id="i1")
        assert conn is fake
        assert fake.executed == ["USE [sales]"]

    def test_parse_mssql_version_success_and_failure(self, monkeypatch):
        monkeypatch.setattr(
            ms_utils,
            "execute_readonly_query",
            lambda *a, **k: [{"version": "Microsoft SQL Server 2019", "product_version": "15.0.2000"}],
        )
        info = ms_utils.parse_mssql_version()
        assert info == {"full_version": "Microsoft SQL Server 2019", "version_number": "15.0.2000", "major_version": 15}

        def boom(*a, **k):
            raise RuntimeError("down")

        monkeypatch.setattr(ms_utils, "execute_readonly_query", boom)
        assert ms_utils.parse_mssql_version()["major_version"] == 0

    def test_format_duration_units(self):
        assert ms_utils.format_duration(None) == "0ms"
        assert ms_utils.format_duration(0.5) == "500.00μs"
        assert ms_utils.format_duration(1500) == "1.50s"
        assert ms_utils.format_duration(120000) == "2.00min"
        assert ms_utils.format_duration(7200000) == "2.00h"
