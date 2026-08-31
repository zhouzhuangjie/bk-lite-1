"""SSH 配置文件节点参数：主机标签、单实例目标与凭据扩展。"""
from types import SimpleNamespace

import pytest

from apps.cmdb.node_configs.ssh.config_file import ConfigFileNodeParams

pytestmark = pytest.mark.unit


def _task(**overrides):
    data = dict(
        id=7,
        model_id="config_file",
        timeout=30,
        params={"config_file_path": "/etc/nginx/nginx.conf", "target_model_id": "host"},
        instances=[
            {
                "_id": "101",
                "model_id": "host",
                "inst_name": "web",
                "ip_addr": "10.0.0.8",
                "cloud_id": "cloud-a",
            }
        ],
        ip_range="10.0.0.0/24",
        access_point=[{"id": 3}],
        decrypt_credentials={"username": "root", "password": "secret", "port": 22},
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def test_instance_host_prefers_inst_name_and_cloud_label():
    params = ConfigFileNodeParams(_task())
    assert params._get_instance_host("bad") == ""
    assert params._get_instance_host({}) == ""
    assert params._get_instance_host({"ip_addr": "10.0.0.8", "inst_name": "10.0.0.8[az1]"}) == "10.0.0.8[az1]"
    assert params._get_instance_host({"ip_addr": "10.0.0.8", "cloud_id": "az1"}) == "10.0.0.8[az1]"
    assert params._get_instance_host({"host": "10.0.0.9"}) == "10.0.0.9"
    assert params._get_connect_ip(" 10.0.0.8[az1] ") == "10.0.0.8"
    assert params._get_connect_ip("") == ""
    assert params._get_instance_id("x") == ""
    assert params._get_instance_id({"id": 5}) == "5"


def test_get_hosts_joins_instances_or_falls_back_to_ip_range():
    params = ConfigFileNodeParams(_task())
    assert params.get_hosts() == ("hosts", "10.0.0.8[cloud-a]")
    empty = ConfigFileNodeParams(_task(instances=[]))
    assert empty.get_hosts() == ("hosts", "10.0.0.0/24")


def test_set_credential_adds_config_file_target_for_single_instance():
    params = ConfigFileNodeParams(_task())
    cred = params.set_credential()
    assert cred["config_file_path"] == "/etc/nginx/nginx.conf"
    assert cred["collect_task_id"] == 7
    assert cred["target_model_id"] == "host"
    assert cred["callback_subject"] == "receive_config_file_result"
    assert cred["target_instance_id"] == "101"
    assert cred["connect_ip"] == "10.0.0.8"
    assert cred["username"] == "root"

    multi = ConfigFileNodeParams(_task(instances=[{}, {"_id": "2"}]))
    cred = multi.set_credential()
    assert "target_instance_id" not in cred
    assert cred["target_model_id"] == "host"
