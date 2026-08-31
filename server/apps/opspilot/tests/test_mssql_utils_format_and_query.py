"""MSSQL 工具：标识符引用、体积/时长格式化与只读查询（不依赖 unixodbc）。"""
import sys
from unittest.mock import MagicMock, patch

import pytest


class _PyodbcError(Exception):
    pass


_fake_pyodbc = MagicMock()
_fake_pyodbc.Error = _PyodbcError
_fake_pyodbc.drivers.return_value = []
sys.modules["pyodbc"] = _fake_pyodbc

from apps.opspilot.metis.llm.tools.mssql import utils as mssql_utils  # noqa: E402

pytestmark = pytest.mark.unit


def test_quote_identifier_and_formatters():
    assert mssql_utils.quote_database_identifier("master") == "[master]"
    with pytest.raises(ValueError, match="非法的数据库名"):
        mssql_utils.quote_database_identifier("bad]name")
    assert mssql_utils.format_size(None) == "0 B"
    assert mssql_utils.format_size(512) == "512.00 B"
    assert mssql_utils.format_size(1024 ** 6) == "1.00 EB"
    assert mssql_utils.format_duration(None) == "0ms"
    assert mssql_utils.format_duration(0.5).endswith("μs")
    assert mssql_utils.format_duration(20) == "20.00ms"
    assert mssql_utils.format_duration(2500) == "2.50s"
    dumped = mssql_utils.safe_json_dumps({"size_bytes": 2048})
    assert "size_bytes_display" in dumped
    assert mssql_utils.calculate_percentage(1, 0) == 0.0
    assert mssql_utils.calculate_percentage(1, 4) == 25.0


def test_execute_readonly_query_success_and_error():
    cursor = MagicMock()
    cursor.description = [("id",), ("name",)]
    cursor.fetchall.return_value = [(1, "a")]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    with (
        patch("apps.opspilot.metis.llm.tools.mssql.utils.run_blocking", side_effect=lambda fn: fn()),
        patch("apps.opspilot.metis.llm.tools.mssql.utils.get_db_connection", return_value=conn),
    ):
        rows = mssql_utils.execute_readonly_query("SELECT 1", params=(1,))
    assert rows == [{"id": 1, "name": "a"}]
    cursor.execute.assert_called_once_with("SELECT 1", (1,))
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()

    conn.cursor.side_effect = _PyodbcError("boom")
    with (
        patch("apps.opspilot.metis.llm.tools.mssql.utils.run_blocking", side_effect=lambda fn: fn()),
        patch("apps.opspilot.metis.llm.tools.mssql.utils.get_db_connection", return_value=conn),
    ):
        with pytest.raises(_PyodbcError):
            mssql_utils.execute_readonly_query("SELECT 1")
