"""拓扑解析纯函数：MAC/IPv4/CDP/LLDP 解码、邻接质量与设备聚合。"""
from apps.cmdb.collection.collect_plugin.topology.models import NormalizedPort
from apps.cmdb.collection.collect_plugin.topology.parse import (
    _index_devices,
    _index_ports,
    infer_topology,
    LLDP_CHASSIS_SUBTYPE_MAC_ADDRESS,
    LLDP_CHASSIS_SUBTYPE_NETWORK_ADDRESS,
    LLDP_PORT_SUBTYPE_AGENT_CIRCUIT_ID,
    LLDP_PORT_SUBTYPE_INTERFACE_ALIAS,
    LLDP_PORT_SUBTYPE_INTERFACE_NAME,
    LLDP_PORT_SUBTYPE_LOCAL,
    LLDP_PORT_SUBTYPE_MAC_ADDRESS,
    LLDP_PORT_SUBTYPE_NETWORK_ADDRESS,
    LLDP_PORT_SUBTYPE_PORT_COMPONENT,
    _iter_device_items,
    decode_cdp_address,
    decode_ipv4ish,
    decode_lldp_chassis_id,
    decode_lldp_port_id,
    extract_previous_links,
    get_neighbor_identifier_quality,
    make_interface_inst_name,
    normalize_mac,
    normalize_mac_from_oid_suffix,
)


def test_extract_previous_links_from_topology_and_relationships():
    assert extract_previous_links("bad") == []
    assert extract_previous_links({"topology": "x"}) == []
    topo = extract_previous_links(
        {
            "topology": {
                "authoritative_links": [{"id": 1}, "skip"],
                "inferred_links": [{"id": 2}],
            }
        }
    )
    assert topo == [{"id": 1}, {"id": 2}]
    rels = extract_previous_links({"topology": "legacy", "relationships": [{"id": 3}, "x"]})
    assert rels == [{"id": 3}]
    assert extract_previous_links({"topology": None, "relationships": "nope"}) == []


def test_normalize_mac_and_oid_suffix():
    assert normalize_mac("") == ""
    assert normalize_mac("0xAABBCCDDEEFF") == "aa:bb:cc:dd:ee:ff"
    assert normalize_mac("aa:bb:cc:dd:ee:ff") == "aa:bb:cc:dd:ee:ff"
    assert normalize_mac_from_oid_suffix("") == ""
    assert normalize_mac_from_oid_suffix("10.20.30.40.50.60") == "0a:14:1e:28:32:3c"
    assert normalize_mac_from_oid_suffix("aabbccddeeff") == "aa:bb:cc:dd:ee:ff"


def test_decode_ipv4ish_and_cdp_address():
    assert decode_ipv4ish("") == ""
    assert decode_ipv4ish("10.0.0.1") == "10.0.0.1"
    assert decode_ipv4ish("1.10.0.0.1") == "10.0.0.1"
    assert decode_ipv4ish("0xc0a80001") == "192.168.0.1"
    assert decode_ipv4ish("0xZZ") == "0xZZ"
    assert decode_cdp_address("1", "") == ""
    assert decode_cdp_address("1", "0x010a000001") == "10.0.0.1"
    assert decode_cdp_address("1", "0xZZ") == "0xZZ"
    assert decode_cdp_address("mac", "0xc0a80001") == "192.168.0.1"


def test_decode_lldp_port_and_chassis():
    assert decode_lldp_port_id(LLDP_PORT_SUBTYPE_INTERFACE_NAME, "Gi0/1") == ("Gi0/1", 100)
    assert decode_lldp_port_id(LLDP_PORT_SUBTYPE_INTERFACE_ALIAS, "uplink") == ("uplink", 100)
    assert decode_lldp_port_id(LLDP_PORT_SUBTYPE_MAC_ADDRESS, "aabbccddeeff") == ("aa:bb:cc:dd:ee:ff", 80)
    assert decode_lldp_port_id(LLDP_PORT_SUBTYPE_NETWORK_ADDRESS, "10.0.0.1") == ("10.0.0.1", 60)
    assert decode_lldp_port_id(LLDP_PORT_SUBTYPE_LOCAL, "local") == ("local", 50)
    assert decode_lldp_port_id(LLDP_PORT_SUBTYPE_PORT_COMPONENT, "pc") == ("pc", 30)
    assert decode_lldp_port_id(LLDP_PORT_SUBTYPE_AGENT_CIRCUIT_ID, "ac") == ("ac", 30)
    assert decode_lldp_port_id("99", "other") == ("other", 40)

    assert decode_lldp_chassis_id(LLDP_CHASSIS_SUBTYPE_MAC_ADDRESS, "") == ""
    assert decode_lldp_chassis_id(LLDP_CHASSIS_SUBTYPE_MAC_ADDRESS, "aabbccddeeff") == "aa:bb:cc:dd:ee:ff"
    assert decode_lldp_chassis_id(LLDP_CHASSIS_SUBTYPE_NETWORK_ADDRESS, "10.0.0.2") == "10.0.0.2"
    assert decode_lldp_chassis_id("7", "keep") == "keep"


def test_neighbor_quality_and_interface_name():
    assert get_neighbor_identifier_quality("cdp", "5", "Gi0/1") == 5
    assert get_neighbor_identifier_quality("cdp", "5", "  ") == 0
    assert get_neighbor_identifier_quality("lldp", LLDP_PORT_SUBTYPE_INTERFACE_NAME, "x") == 10
    assert get_neighbor_identifier_quality("lldp", LLDP_PORT_SUBTYPE_MAC_ADDRESS, "x") == 5
    assert get_neighbor_identifier_quality("lldp", LLDP_PORT_SUBTYPE_NETWORK_ADDRESS, "x") == 0
    assert get_neighbor_identifier_quality("lldp", LLDP_PORT_SUBTYPE_LOCAL, "x") == 0
    assert get_neighbor_identifier_quality("lldp", "99", "x") == 0
    assert make_interface_inst_name("sw1", None) == "sw1-unknown"
    port = NormalizedPort(device_id="sw1", port_id="1", ifindex="1", ifname="Gi0/1")
    assert make_interface_inst_name("sw1", port) == "sw1-Gi0/1"


def test_iter_device_items_errors_and_legacy_evidence():
    items, errors = _iter_device_items(
        {
            "devices": [
                "skip",
                {"device": {"host": "sw-err"}, "success": False, "error": "timeout", "collector_result": {"result": {}}},
                {
                    "device": {"host": "sw1"},
                    "success": True,
                    "collector_result": {
                        "result": {
                            "network_topo": [
                                "skip",
                                {"tag": "ARP-1", "val": "a"},
                                {"tag": "IF-1", "val": "b"},
                                {"tag": "IpAddr-1", "val": "c"},
                                {"tag": "System-SysName", "val": "core"},
                            ]
                        }
                    },
                },
            ]
        }
    )
    assert errors == [{"device_id": "sw-err", "error": "timeout"}]
    assert len(items) == 1
    assert items[0]["device_id"] == "sw1"
    assert items[0]["evidence"]["arp"] == [{"tag": "ARP-1", "val": "a"}]
    assert items[0]["evidence"]["interfaces"] == [{"tag": "IF-1", "val": "b"}]
    assert items[0]["evidence"]["ip"] == [{"tag": "IpAddr-1", "val": "c"}]
    assert items[0]["evidence"]["system"] == [{"tag": "System-SysName", "val": "core"}]


def test_index_and_infer_unresolved_local_port():
    normalized = {
        "ports": [
            "skip",
            {
                "device_id": "sw1",
                "port_id": "sw1:1",
                "ifindex": "1",
                "ifname": "Gi0/1",
                "mac": "aa:bb:cc:dd:ee:ff",
            },
        ],
        "devices": ["skip", {"device_id": "sw1", "host": "10.0.0.1", "sys_name": "core"}],
        "neighbor_observations": [
            "skip",
            {"local_port_id": "missing", "protocol": "lldp", "evidence_key": "e1", "source_device_id": "sw1"},
        ],
        "arp_observations": ["skip"],
        "fdb_observations": ["skip"],
    }
    ports = _index_ports(normalized)
    assert ports["sw1:1"].ifname == "Gi0/1"
    devices = _index_devices(normalized)
    assert devices["sw1"]["host"] == "10.0.0.1"
    out = infer_topology(normalized)
    assert out["authoritative_links"] == []
    assert out["unresolved_neighbors"][0]["resolution_state"] == "unresolved_local_port"
    assert out["unresolved_neighbors"][0]["decision_reason"] == (
        "Could not map the local neighbor port to a normalized interface."
    )
