"""CollectModelSerializer.validate：配置文件路径/设备校验与 SNMP 拓扑归一化。"""
import pytest
from rest_framework.exceptions import ValidationError

from apps.cmdb.constants.constants import CollectPluginTypes
from apps.cmdb.serializers.collect_serializer import CollectModelSerializer

pytestmark = pytest.mark.unit


def _serializer():
    ser = object.__new__(CollectModelSerializer)
    ser.instance = None
    return ser


def test_validate_host_task_passthrough():
    attrs = {"task_type": CollectPluginTypes.HOST, "model_id": "host", "name": "t"}
    assert _serializer().validate(attrs)["name"] == "t"


def test_validate_snmp_normalizes_topology_when_disabled():
    attrs = _serializer().validate(
        {
            "task_type": CollectPluginTypes.SNMP,
            "model_id": "switch",
            "params": {"has_network_topo": False},
        }
    )
    assert "topology_protocols" in attrs["params"]
    assert attrs["params"]["has_network_topo"] is False


def test_validate_config_file_requires_host_and_absolute_path():
    with pytest.raises(ValidationError) as err:
        _serializer().validate(
            {
                "task_type": CollectPluginTypes.CONFIG_FILE,
                "model_id": "host",
                "params": {"config_file_path": "relative.conf"},
            }
        )
    assert "params" in err.value.detail

    with pytest.raises(ValidationError, match="请选择主机"):
        _serializer().validate(
            {
                "task_type": CollectPluginTypes.CONFIG_FILE,
                "model_id": "host",
                "params": {"config_file_path": "/etc/app.conf"},
                "instances": [],
            }
        )


def test_validate_network_config_file_requires_devices():
    with pytest.raises(ValidationError, match="请选择网络设备"):
        _serializer().validate(
            {
                "task_type": CollectPluginTypes.CONFIG_FILE,
                "model_id": "network_config_file",
                "instances": [],
            }
        )
