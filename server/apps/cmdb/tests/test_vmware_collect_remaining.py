"""CollectVmwareMetrics：关联构造、实例名、磁盘与 format_metrics 字段映射。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.cmdb.collection.collect_plugin.vmware import CollectVmwareMetrics

pytestmark = pytest.mark.unit


def _collector():
    obj = CollectVmwareMetrics.__new__(CollectVmwareMetrics)
    obj.inst_name = "VC-1"
    obj.model_resource_id_mapping = {
        "vmware_ds": {"ds1": "DS-1", "ds2": "DS-2"},
        "vmware_esxi": {"esxi-1": "ESXI-1"},
    }
    obj.timestamp_gt = False
    obj.collection_metrics_dict = {"vmware_vc": [], "vmware_vm": []}
    obj.result = {}
    return obj


def test_vmware_association_and_name_helpers():
    c = _collector()
    esxi = c.get_esxi_asso({"vmware_ds": "ds1,ds2"})
    assert esxi[0]["model_asst_id"] == "vmware_esxi_group_vmware_vc"
    assert esxi[1]["inst_name"] == "DS-1"
    assert esxi[2]["inst_name"] == "DS-2"

    vm = c.get_vm_asso({"vmware_esxi": "esxi-1", "vmware_ds": "ds1,missing"})
    assert vm[0] == {
        "model_id": "vmware_esxi",
        "inst_name": "ESXI-1",
        "asst_id": "run",
        "model_asst_id": "vmware_vm_run_vmware_esxi",
    }
    assert [i["inst_name"] for i in vm[1:]] == ["DS-1"]
    assert c.get_vm_asso({"vmware_esxi": "gone", "vmware_ds": ""}) == []

    assert c.get_vm_esxi_name({"vmware_esxi": "esxi-1"}) == "ESXI-1"
    assert c.get_vm_esxi_name({"vmware_esxi": "gone"}) == ""
    assert CollectVmwareMetrics.set_inst_name({"inst_name": "vm-a", "resource_id": "moid-1"}) == "vm-a[moid-1]"
    assert c.set_vc_inst_name({"instance_id": "prefix_dc_name"}) == "VC-1"
    c.inst_name = ""
    assert c.set_vc_inst_name({"instance_id": "prefix_dc_name"}) == "dc_name"
    assert c.set_data_disks({"data_disks": '\\"ssd\\"'}) == '"ssd"'
    assert c.set_data_disks({}) == ""


def test_format_data_skips_failed_and_old_samples():
    c = _collector()
    c.collection_metrics_dict = {"vm_cpu": []}
    with patch("apps.cmdb.collection.collect_plugin.vmware.timestamp_gt_one_day_ago", return_value=True):
        c.format_data(
            {
                "result": [
                    {"metric": {"__name__": "vm_cpu", "collect_status": "failed"}, "value": [1, "1"]},
                    {"metric": {"__name__": "vm_cpu"}, "value": [10, "2"]},
                ]
            }
        )
    assert c.collection_metrics_dict["vm_cpu"] == []

    with patch("apps.cmdb.collection.collect_plugin.vmware.timestamp_gt_one_day_ago", return_value=False):
        c.format_data(
            {
                "result": [
                    {"metric": {"__name__": "vm_cpu", "collect_status": "ok", "host": "h1"}, "value": [20, "9"]},
                ]
            }
        )
    assert c.timestamp_gt is True
    assert c.collection_metrics_dict["vm_cpu"][0]["index_value"] == "9"
    assert c.collection_metrics_dict["vm_cpu"][0]["host"] == "h1"


def test_format_metrics_applies_mapping_and_swallows_convert_errors():
    c = _collector()
    c.collection_metrics_dict = {
        "vmware_vc": [{"resource_id": "1", "inst_name": ""}, {"resource_id": "2", "inst_name": "VC", "cpu": "bad", "mem": "8"}],
        "vmware_vm": [{"resource_id": "v1", "inst_name": "vm1", "path": "C\\\\Users"}],
    }

    def boom(_raw):
        raise ValueError("not int")

    mapping = {
        "vmware_vc": {
            "cpu": (boom, "cpu"),
            "skip": (int, "missing"),
            "mem": (int, "mem"),
            "name": lambda data, name: name,
            "fail_fn": lambda data, name: (_ for _ in ()).throw(RuntimeError("fn")),
        },
        "vmware_vm": {"path": "path"},
    }
    with (
        patch(
            "apps.cmdb.collection.collect_plugin.vmware.VMWARE_COLLECT_MAP",
            {"vmware_vc": "vmware_vc", "vmware_vm": "vmware_vm"},
        ),
        patch.object(
            CollectVmwareMetrics,
            "model_field_mapping",
            new=property(lambda self: mapping),
        ),
    ):
        c.format_metrics()
    assert c.result["vmware_vc"] == [{"mem": 8, "name": "VC"}]
    assert c.result["vmware_vm"] == [{"path": "CUsers"}]
