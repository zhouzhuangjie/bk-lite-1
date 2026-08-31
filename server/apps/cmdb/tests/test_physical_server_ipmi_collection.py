"""IPMI 物理服务器采集：实例名优先级、失败指标跳过与空值不覆盖。"""
from unittest.mock import patch

import pytest

from apps.cmdb.collection.plugins.community.protocol.physical_server import PhysicalServerIPMICollectionPlugin

pytestmark = pytest.mark.unit


def _plugin():
    return PhysicalServerIPMICollectionPlugin("seed", 1, 99)


def test_get_inst_name_prefers_serial_then_ip_then_model():
    plugin = _plugin()
    assert plugin.get_inst_name({"serial_number": "SN-1", "ip_addr": "10.0.0.1"}) == "SN-1"
    assert plugin.get_inst_name({"ip_addr": "10.0.0.1", "model": "R740"}) == "10.0.0.1"
    assert plugin.get_inst_name({"model": "R740"}) == "R740"
    assert plugin.get_inst_name({}) == "physcial_server"


def test_format_data_skips_failed_and_unknown_metrics():
    plugin = _plugin()
    plugin.format_data("not-a-dict")
    plugin.format_data(
        {
            "result": [
                {"metric": {"__name__": "other_gauge", "collect_status": "ok"}},
                {"metric": {"__name__": "physcial_server_info_gauge", "collect_status": "failed"}},
                {
                    "metric": {
                        "__name__": "physcial_server_info_gauge",
                        "collect_status": "ok",
                        "serial_number": "SN-9",
                        "ip_addr": "10.0.0.8",
                        "model": "R740",
                        "brand": "Dell",
                    }
                },
            ]
        }
    )
    assert plugin.collection_metrics_dict["physcial_server_info_gauge"][0]["serial_number"] == "SN-9"


def test_format_metrics_skips_empty_values_and_sets_inst_name():
    plugin = _plugin()
    plugin.collection_metrics_dict["physcial_server_info_gauge"] = [
        {"serial_number": "SN-9", "ip_addr": "", "model": "R740", "brand": None}
    ]
    with patch.object(PhysicalServerIPMICollectionPlugin, "model_id", "physcial_server"):
        mapping = dict(plugin.field_mapping)
        mapping["inst_name"] = plugin.get_inst_name
        with patch.object(type(plugin), "model_field_mapping", {"physcial_server": mapping}):
            plugin.format_metrics()
    rows = plugin.result["physcial_server"]
    assert rows == [{"serial_number": "SN-9", "model": "R740", "inst_name": "SN-9"}]
