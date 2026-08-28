"""Host / 网络设备实例 ID 适配：统一 storage key，缺 cloud_region/ip 拒绝。"""
import pytest

from apps.monitor.services.node_mgmt import InstanceConfigService as SVC

pytestmark = pytest.mark.unit


def test_should_use_identity_adapters_by_object_name():
    assert SVC._should_use_host_identity_adapter("Host") is True
    assert SVC._should_use_host_identity_adapter("Switch") is False
    assert SVC._should_use_network_device_identity_adapter("Switch") is True
    assert SVC._should_use_network_device_identity_adapter("Router") is True
    assert SVC._should_use_network_device_identity_adapter("Host") is False


def test_prepare_host_identity_rewrites_instance_id():
    from apps.monitor.utils.dimension import normalize_instance_identity

    instances = [{"instance_id": "1.2.3.4", "instance_name": "h1", "group_ids": [1]}]
    out = SVC._prepare_host_identity_instances(instances)
    expected_key = normalize_instance_identity("1.2.3.4")["storage_instance_key"]
    assert len(out) == 1
    assert out[0]["raw_instance_id"] == "1.2.3.4"
    assert out[0]["storage_instance_key"] == expected_key
    assert out[0]["instance_id"] == expected_key
    assert out[0]["instance_id"] != "1.2.3.4"
    assert out[0]["instance_name"] == "h1"


def test_extract_network_device_parts_from_fields_and_encoded_id():
    assert SVC._extract_network_device_identity_parts({"cloud_region_id": 2, "ip": "10.0.0.8"}) == (2, "10.0.0.8")
    cloud, ip = SVC._extract_network_device_identity_parts({"instance_id": "3:default:10.1.1.1"})
    assert str(cloud) == "3"
    assert ip == "10.1.1.1"
    cloud2, ip2 = SVC._extract_network_device_identity_parts({"instance_id": "8_10.2.2.2"})
    assert str(cloud2) == "8"
    assert ip2 == "10.2.2.2"
    with pytest.raises(ValueError, match="cloud_region and ip"):
        SVC._extract_network_device_identity_parts({"instance_id": "orphan"})


def test_prepare_network_device_identity_sets_storage_key():
    instances = [{"instance_id": "x", "cloud_region_id": 1, "ip": "10.0.0.9", "group_ids": [1]}]
    out = SVC._prepare_network_device_identity_instances(instances)
    assert out[0]["raw_instance_id"] == "x"
    assert out[0]["instance_id"] == out[0]["storage_instance_key"]
    assert out[0]["logical_instance_value"]
