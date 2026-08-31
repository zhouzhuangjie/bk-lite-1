"""QCloud / VMware / 物理机 IPMI NodeParams 凭据与环境变量契约。"""
from types import SimpleNamespace

import pytest

from apps.cmdb.node_configs.cloud.qcloud import QCloudNodeParams
from apps.cmdb.node_configs.cloud.vmware import VmwareNodeParams
from apps.cmdb.node_configs.protocol.physcial_server import PhysicalServerIPMINodeParams

pytestmark = pytest.mark.unit


def _instance(model_id, credential, instances, driver_type="protocol"):
    return SimpleNamespace(
        id=7,
        model_id=model_id,
        driver_type=driver_type,
        timeout=30,
        decrypt_credentials=credential,
        instances=instances,
        params={},
        ip_range="",
        access_point=[{"id": "n1"}],
    )


def test_qcloud_node_params_credential_env_and_region_builder():
    inst = _instance(
        "qcloud",
        {"accessKey": "AKID", "accessSecret": "SK"},
        [{"endpoint": "https://cvm.tencentcloudapi.com"}],
    )
    node = QCloudNodeParams(inst)
    assert node.host_field == "endpoint"
    cred = node.set_credential()
    assert cred == {
        "secret_id": "${PASSWORD_secret_id_cmdb_7}",
        "secret_key": "${PASSWORD_secret_key_cmdb_7}",
    }
    assert node.env_config() == {
        "PASSWORD_secret_id_cmdb_7": "AKID",
        "PASSWORD_secret_key_cmdb_7": "SK",
    }
    built = QCloudNodeParams.build_region_credential({"access_key": "AK", "access_secret": "SS", "cloud_id": 1})
    assert built == {"secret_id": "AK", "secret_key": "SS"}
    fallback = QCloudNodeParams.build_region_credential({"accessKey": "A2", "accessSecret": "S2"})
    assert fallback == {"secret_id": "A2", "secret_key": "S2"}
    assert node.password == {"secret_id": "AKID", "secret_key": "SK"}


def test_vmware_node_params_hosts_credential_and_env():
    inst = _instance(
        "vmware_vc",
        {"username": "admin", "password": "p@ss", "port": 8443, "ssl": True},
        [{"ip_addr": "10.1.2.3"}],
    )
    node = VmwareNodeParams(inst)
    assert node.get_hosts() == ("hostname", "10.1.2.3")
    cred = node.set_credential()
    assert cred["username"] == "admin"
    assert cred["password"] == "${PASSWORD_password_cmdb_7}"
    assert cred["port"] == 8443
    assert cred["ssl"] == "true"
    assert node.env_config() == {"PASSWORD_password_cmdb_7": "p@ss"}


def test_physical_server_ipmi_node_params_optional_privilege():
    inst = _instance(
        "physcial_server",
        {"username": "root", "password": "ipmi", "port": 624, "privilege": "administrator"},
        [{"ip_addr": "10.0.0.8"}],
    )
    node = PhysicalServerIPMINodeParams(inst)
    assert node.host_field == "ip_addr"
    assert node.executor_type == "protocol"
    cred = node.set_credential()
    assert cred == {
        "port": 624,
        "username": "root",
        "password": "${PASSWORD_password_cmdb_7}",
        "privilege": "administrator",
    }
    assert node.env_config() == {"PASSWORD_password_cmdb_7": "ipmi"}

    inst.decrypt_credentials = {"user": "bmc"}
    node = PhysicalServerIPMINodeParams(inst)
    cred = node.set_credential()
    assert cred["username"] == "bmc"
    assert cred["port"] == 623
    assert "privilege" not in cred
