"""CollectTargetService：IP 范围展开与 object_key 生成。"""
from types import SimpleNamespace

import pytest

from apps.cmdb.constants.constants import CollectPluginTypes
from apps.cmdb.services.collect_target_service import CollectTargetService, CanonicalCollectTarget

pytestmark = pytest.mark.unit


def test_expand_ip_range_empty_csv_and_hyphen_range():
    assert CollectTargetService._expand_ip_range(None) == []
    assert CollectTargetService._expand_ip_range("") == []
    assert CollectTargetService._expand_ip_range("10.0.0.1, 10.0.0.2") == ["10.0.0.1", "10.0.0.2"]
    assert CollectTargetService._expand_ip_range("10.0.0.1-10.0.0.3") == [
        "10.0.0.1",
        "10.0.0.2",
        "10.0.0.3",
    ]
    # 起止颠倒会交换
    assert CollectTargetService._expand_ip_range("10.0.0.3-10.0.0.1") == [
        "10.0.0.1",
        "10.0.0.2",
        "10.0.0.3",
    ]
    # 非法区间当作字面量
    assert CollectTargetService._expand_ip_range("not-an-ip") == ["not-an-ip"]


def test_build_targets_from_ip_range_and_instances():
    task = SimpleNamespace(
        id=8,
        task_type=CollectPluginTypes.HOST,
        is_job=False,
        model_id="host",
        instances=[],
        ip_range="192.168.1.1,192.168.1.2",
        params={},
        decrypt_credentials={},
    )
    targets = CollectTargetService.build_targets(task)
    assert [t.host for t in targets] == ["192.168.1.1", "192.168.1.2"]
    assert all(t.task_id == 8 for t in targets)

    task.instances = [{"ip": "10.1.1.1", "host": "10.1.1.1"}]
    inst_targets = CollectTargetService.build_targets(task)
    assert len(inst_targets) == 1


def test_build_object_key_by_task_type():
    host = CanonicalCollectTarget(task_id=1, task_type=CollectPluginTypes.HOST, executor="job", model_id="host", host="h1", cloud_region_id="3")
    assert CollectTargetService.build_object_key(host) == "1:h1:3"
    db = CanonicalCollectTarget(task_id=2, task_type=CollectPluginTypes.DB, executor="protocol", model_id="mysql", host="db", port=3306)
    assert CollectTargetService.build_object_key(db) == "2:db:-:3306"
    snmp = CanonicalCollectTarget(task_id=3, task_type=CollectPluginTypes.SNMP, executor="protocol", model_id="switch", host="sw", port=161, cloud_region_id="9")
    assert CollectTargetService.build_object_key(snmp) == "3:sw:161:9"
