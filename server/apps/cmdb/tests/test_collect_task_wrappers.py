"""CMDB 采集任务薄封装：get_collect_plugin 转发与 ProtocolCollect.main。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.cmdb.collection.collect_tasks.aliyun import AliyunCollect
from apps.cmdb.collection.collect_tasks.aws import AWSCollect
from apps.cmdb.collection.collect_tasks.databases import DBCollect
from apps.cmdb.collection.collect_tasks.host import HostCollect
from apps.cmdb.collection.collect_tasks.k8s import K8sCollect
from apps.cmdb.collection.collect_tasks.middleware import MiddlewareCollect
from apps.cmdb.collection.collect_tasks.network import NetworkCollect
from apps.cmdb.collection.collect_tasks.protocol import ProtocolTaskCollect
from apps.cmdb.collection.collect_tasks.protocol_collect import ProtocolCollect
from apps.cmdb.collection.collect_tasks.qcloud import QCloudCollect
from apps.cmdb.collection.collect_tasks.registry import RegisteredCollect
from apps.cmdb.collection.collect_tasks.vmware import VmwareCollect

pytestmark = pytest.mark.unit

WRAPPERS = [
    (AliyunCollect, "apps.cmdb.collection.collect_tasks.aliyun.get_collection_plugin", "cloud", "aliyun"),
    (AWSCollect, "apps.cmdb.collection.collect_tasks.aws.get_collection_plugin", "cloud", "aws"),
    (K8sCollect, "apps.cmdb.collection.collect_tasks.k8s.get_collection_plugin", "k8s", "k8s"),
    (NetworkCollect, "apps.cmdb.collection.collect_tasks.network.get_collection_plugin", "snmp", "network"),
    (ProtocolTaskCollect, "apps.cmdb.collection.collect_tasks.protocol.get_collection_plugin", "protocol", "host"),
    (QCloudCollect, "apps.cmdb.collection.collect_tasks.qcloud.get_collection_plugin", "cloud", "qcloud"),
    (VmwareCollect, "apps.cmdb.collection.collect_tasks.vmware.get_collection_plugin", "cloud", "vmware_vc"),
    (HostCollect, "apps.cmdb.collection.collect_tasks.host.get_collection_plugin", "host", "host"),
    (DBCollect, "apps.cmdb.collection.collect_tasks.databases.get_collection_plugin", "db", "mysql"),
    (MiddlewareCollect, "apps.cmdb.collection.collect_tasks.middleware.get_collection_plugin", "middleware", "nginx"),
    (RegisteredCollect, "apps.cmdb.collection.collect_tasks.registry.get_collection_plugin", "protocol", "snmp"),
]


def _task(task_type, model_id):
    return SimpleNamespace(
        id=1,
        instances=[],
        team=[1],
        params={},
        model_id=model_id,
        is_host=False,
        is_k8s=False,
        task_type=task_type,
        input_method=0,
        data_cleanup_strategy=None,
    )


@pytest.mark.parametrize("cls,patch_path,task_type,model_id", WRAPPERS)
def test_collect_wrappers_forward_plugin_lookup(cls, patch_path, task_type, model_id):
    with patch(patch_path, return_value="plugin-cls") as getter:
        collector = cls(1, task=_task(task_type, model_id))
        assert collector.get_collect_plugin() == "plugin-cls"
    getter.assert_called_once_with(task_type, model_id)


def test_protocol_collect_main_invokes_registered_collect():
    task = SimpleNamespace(id=42)

    class _Callable:
        def __init__(self, *a, **k):
            self.args = a
            self.kwargs = k

        def __call__(self):
            return {"ok": True, "task_id": self.args[0]}

    with patch("apps.cmdb.collection.collect_tasks.protocol_collect.RegisteredCollect", _Callable):
        assert ProtocolCollect(task, default_metrics=["up"]).main() == {"ok": True, "task_id": 42}
