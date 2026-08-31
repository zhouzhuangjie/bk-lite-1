"""MySQL connection 剩余契约：按名解析失败、SSL key、探测与适配器校验。"""
from unittest.mock import MagicMock

import pytest

from apps.opspilot.metis.llm.tools.common.credentials import CredentialValidationError
from apps.opspilot.metis.llm.tools.mysql import connection as my_conn

pytestmark = pytest.mark.unit


def test_resolve_by_name_not_found():
    with pytest.raises(ValueError, match="MySQL instance not found: ghost"):
        my_conn.resolve_mysql_instance([{"id": "a", "name": "A"}], instance_name="ghost")


def test_build_config_includes_ssl_key():
    params = my_conn.build_mysql_config_from_instance(
        {"host": "h", "ssl": True, "ssl_ca": "/ca.pem", "ssl_cert": "/c.pem", "ssl_key": "/k.pem"}
    )
    assert params["ssl_ca"] == "/ca.pem"
    assert params["ssl_cert"] == "/c.pem"
    assert params["ssl_key"] == "/k.pem"


def test_get_mysql_connection_uses_selected_instance(mocker):
    created = mocker.patch.object(my_conn, "_create_mysql_connection", return_value="CONN")
    cfg = {
        "configurable": {
            "mysql_instances": [
                {"id": "a", "host": "h1", "name": "A"},
                {"id": "b", "host": "h2", "name": "B"},
            ]
        }
    }
    assert my_conn.get_mysql_connection(cfg, instance_id="b") == "CONN"
    assert created.call_args[0][0]["host"] == "h2"


def test_get_mysql_connection_legacy_rejects_instance_selection():
    with pytest.raises(ValueError, match="legacy single-instance"):
        my_conn.get_mysql_connection({"configurable": {"host": "h"}}, instance_name="A")


def test_get_mysql_connection_legacy_flat(mocker):
    created = mocker.patch.object(my_conn, "_create_mysql_connection", return_value="LEGACY")
    assert my_conn.get_mysql_connection({"configurable": {"host": "legacy", "user": "u"}}) == "LEGACY"
    assert created.call_args[0][0]["host"] == "legacy"


def test_adapter_validate_and_display_name():
    adapter = my_conn.MysqlCredentialAdapter()
    with pytest.raises(CredentialValidationError, match="MySQL host is required"):
        adapter.validate({"host": ""})
    assert adapter.validate({"host": "h"}) is None
    assert adapter.get_display_name({"name": "prod"}, 0) == "prod"
    assert adapter.get_display_name({}, 1) == "MySQL - 2"
    assert adapter.build_from_flat_config({"host": "h", "port": "3307"})["port"] == 3307


def test_mysql_instance_requires_host_and_pings(mocker):
    with pytest.raises(ValueError, match="MySQL host is required"):
        my_conn.test_mysql_instance({})
    conn = MagicMock()
    mocker.patch.object(my_conn, "_create_mysql_connection", return_value=conn)
    assert my_conn.test_mysql_instance({"host": "h"}) is True
    conn.ping.assert_called_once_with(reconnect=False)
    conn.close.assert_called_once()
