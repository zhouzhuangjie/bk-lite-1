"""运维分析 NATS 模块列表/数据与默认客户端转发。"""
from unittest.mock import MagicMock, patch

from apps.operation_analysis.constants.constants import PERMISSION_DATASOURCE, PERMISSION_DIRECTORY
from apps.operation_analysis.nats.nats import get_operation_analysis_module_data, get_operation_analysis_module_list
from apps.operation_analysis.nats.nats_client import DefaultNastClient


def test_operation_analysis_module_list_contract():
    result = get_operation_analysis_module_list()
    assert result[0]["name"] == PERMISSION_DIRECTORY
    assert result[0]["display_name"] == "目录"
    names = [c["name"] for c in result[0]["children"]]
    assert names == ["dashboard", "topology", "architecture"]
    assert result[1] == {"name": PERMISSION_DATASOURCE, "display_name": "数据源", "children": []}


def test_operation_analysis_module_data_delegates_to_directory_service():
    with patch(
        "apps.operation_analysis.nats.nats.DictDirectoryService.get_operation_analysis_module_data",
        return_value={"count": 1, "items": [{"id": 9}]},
    ) as svc:
        out = get_operation_analysis_module_data("directory", "dashboard", 1, 20, 3)
    assert out == {"count": 1, "items": [{"id": 9}]}
    svc.assert_called_once_with(module="directory", child_module="dashboard", page=1, page_size=20, group_id=3)


def test_default_nats_client_runs_named_function():
    client = DefaultNastClient("custom_fn")
    client.client = MagicMock()
    client.client.run.return_value = {"ok": True}
    assert client.get_customization_nast_data(1, k=2) == {"ok": True}
    client.client.run.assert_called_once_with("custom_fn", 1, k=2)
    assert client.DEFAULT_NATS is True
