"""IP 发现 NodeParams：子网查询、CIDR 规范化与扫描端口。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.cmdb.node_configs.ipam.ip_discovery import DEFAULT_SCAN_PORTS, IPDiscoveryNodeParams

pytestmark = pytest.mark.unit


def _inst(params=None, instances=None):
    return SimpleNamespace(
        id=5,
        model_id="ip",
        driver_type="protocol",
        timeout=20,
        decrypt_credentials={},
        instances=instances if instances is not None else {},
        params=params or {},
        ip_range="",
        access_point=[],
    )


def test_ip_discovery_empty_subnets_and_invalid_cidr():
    node = IPDiscoveryNodeParams(_inst(params={"scan_method": "TCP", "ports": 22, "subnet_ids": "  "}))
    assert node.get_hosts() == ("hosts", "")
    assert node.env_config() == {}
    cred = node.set_credential()
    assert cred["scan_method"] == "tcp"
    assert cred["ports"] == "[22]"
    assert cred["subnets"] == "[]"
    assert IPDiscoveryNodeParams._to_cidr("10.0.0.0", "24") == "10.0.0.0/24"
    assert IPDiscoveryNodeParams._to_cidr("bad", "x") == ""
    assert IPDiscoveryNodeParams._to_cidr(None, 24) == ""


def test_ip_discovery_loads_subnet_scopes_and_merges_reserved():
    graph = MagicMock()
    graph.__enter__.return_value = graph
    graph.__exit__.return_value = False
    graph.query_entity.return_value = (
        [
            {"_id": 11, "subnet_address": "10.0.1.0", "subnet_mask": "24", "gateway": "10.0.1.1"},
            {"id": 12, "subnet_address": "", "subnet_mask": "24"},
            {"_id": 13, "subnet_address": "10.0.2.0", "subnet_mask": "24", "gateway": ""},
        ],
        3,
    )
    inst = _inst(
        params={
            "subnet_ids": [11, "13", ""],
            "reserved_addresses": ["10.0.1.254", " "],
            "ports": [22, 443],
        }
    )
    node = IPDiscoveryNodeParams(inst)
    with patch("apps.cmdb.node_configs.ipam.ip_discovery.GraphClient", return_value=graph):
        scopes = node._load_subnet_scopes()
    assert scopes == [
        {
            "subnet_id": 11,
            "cidr": "10.0.1.0/24",
            "gateway": "10.0.1.1",
            "reserved_addresses": ["10.0.1.1", "10.0.1.254"],
        },
        {
            "subnet_id": 13,
            "cidr": "10.0.2.0/24",
            "gateway": "",
            "reserved_addresses": ["10.0.1.254"],
        },
    ]
    graph.query_entity.assert_called_once()
    filters = graph.query_entity.call_args.args[1]
    assert filters[1]["value"] == [11, 13]

    with patch("apps.cmdb.node_configs.ipam.ip_discovery.GraphClient", return_value=graph):
        cred = node.set_credential()
    assert cred["ports"] == "[22, 443]"
    assert '"cidr": "10.0.1.0/24"' in cred["subnets"]
    assert DEFAULT_SCAN_PORTS == [22, 80, 443, 3389]
