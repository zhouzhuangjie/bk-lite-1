"""采集序列化器：实例字段回退、配置文件校验与列表 digest。"""
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.cmdb.constants.constants import CollectDriverTypes, CollectPluginTypes
from apps.cmdb.serializers.collect_serializer import CollectModelLIstSerializer, CollectModelSerializer

pytestmark = pytest.mark.unit


def _ser(instance=None):
    obj = CollectModelSerializer.__new__(CollectModelSerializer)
    obj.instance = instance
    return obj


def test_get_attr_and_effective_params_fall_back_to_instance():
    inst = SimpleNamespace(task_type="snmp", params={"a": 1, "b": 2})
    ser = _ser(inst)
    assert ser._get_attr_or_instance_value({}, "task_type") == "snmp"
    assert ser._get_attr_or_instance_value({"task_type": "http"}, "task_type") == "http"
    assert ser._get_effective_params({}) == {"a": 1, "b": 2}
    assert ser._get_effective_params({"params": {"b": 9}}) == {"a": 1, "b": 9}
    assert _ser(None)._get_effective_params({}) == {}


def test_validate_config_file_requires_absolute_path_and_hosts():
    ser = _ser()
    with pytest.raises(ValidationError, match="请输入有效的配置文件完整绝对路径"):
        ser.validate({"task_type": CollectPluginTypes.CONFIG_FILE, "model_id": "host", "params": {"config_file_path": "relative.conf"}})
    with pytest.raises(ValidationError, match="请选择主机"):
        ser.validate(
            {
                "task_type": CollectPluginTypes.CONFIG_FILE,
                "model_id": "host",
                "params": {"config_file_path": "/etc/a.conf"},
                "instances": [],
            }
        )
    out = ser.validate(
        {
            "task_type": CollectPluginTypes.CONFIG_FILE,
            "model_id": "host",
            "params": {"config_file_path": "/etc/a.conf"},
            "instances": [{"id": 1}],
        }
    )
    assert out["driver_type"] == CollectDriverTypes.JOB
    assert out["ip_range"] == ""
    assert out["params"]["config_file_path"] == "/etc/a.conf"


def test_validate_network_config_file_requires_device_and_name():
    ser = _ser()
    with pytest.raises(ValidationError, match="请选择网络设备"):
        ser.validate({"task_type": CollectPluginTypes.CONFIG_FILE, "model_id": "network_config_file", "instances": []})
    with pytest.raises(ValidationError) as exc:
        ser.validate(
            {
                "task_type": CollectPluginTypes.CONFIG_FILE,
                "model_id": "network_config_file",
                "instances": [{"model_id": "host", "ip_addr": "10.0.0.1"}],
                "params": {},
            }
        )
    assert "instances" in exc.value.detail

    with pytest.raises(ValidationError) as exc:
        ser.validate(
            {
                "task_type": CollectPluginTypes.CONFIG_FILE,
                "model_id": "network_config_file",
                "instances": [{"model_id": "switch", "ip_addr": "10.0.0.1", "brand": "cisco"}],
                "params": {},
            }
        )
    assert "请输入配置名称" in str(exc.value)


def test_list_serializer_message_defaults_when_digest_missing():
    assert CollectModelLIstSerializer.get_message(SimpleNamespace(collect_digest={"add": 1})) == {"add": 1}
    assert CollectModelLIstSerializer.get_message(SimpleNamespace(collect_digest=None)) == {
        "add": 0,
        "update": 0,
        "delete": 0,
        "association": 0,
    }
