"""ToolsNodes._build_diff_report_tool：派发 config_diff_report 并返回可点击文案。"""
import sys
import types
from unittest.mock import patch

for _mod_name in ("oracledb", "pyodbc"):
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))
_falkordb = types.ModuleType("falkordb")
_falkordb.Graph = type("Graph", (), {})
sys.modules.setdefault("falkordb", _falkordb)
_falkordb_asyncio = types.ModuleType("falkordb.asyncio")
_falkordb_asyncio.FalkorDB = type("FalkorDB", (), {})
sys.modules.setdefault("falkordb.asyncio", _falkordb_asyncio)

import pytest

from apps.opspilot.metis.llm.chain.node import ToolsNodes

pytestmark = pytest.mark.unit

ITEMS = [
    {
        "workload_name": "nginx",
        "workload_type": "Deployment",
        "namespace": "prod",
        "severity": "high",
        "summary": "缺少资源限制",
        "before_yaml": "resources: {}",
        "after_yaml": "resources:\n  limits:\n    cpu: 100m",
    }
]


@pytest.mark.asyncio
async def test_report_config_diff_dispatches_payload_and_returns_count():
    tool = ToolsNodes()._build_diff_report_tool()
    captured = []

    def _capture(name, payload, *args, **kwargs):
        captured.append((name, payload))

    with patch("apps.opspilot.metis.llm.chain.node.dispatch_custom_event", _capture):
        result = await tool.coroutine(title="K8S 对比", cluster_name="prod-cluster", items=ITEMS)
    assert result == "已生成配置修复对比报告（1 个工作负载），用户可点击查看详细对比。"
    assert tool.name == "report_config_diff"
    assert len(captured) == 1
    assert captured[0][0] == "config_diff_report"
    payload = captured[0][1]
    assert payload["title"] == "K8S 对比"
    assert payload["cluster_name"] == "prod-cluster"
    assert payload["items"][0]["workload_name"] == "nginx"
    assert payload["items"][0]["before_yaml"] == "resources: {}"
    assert payload["a2ui"]["component"] == "config-diff-report"
    assert payload["a2ui"]["event_name"] == "config_diff_report"
    assert payload["report_id"]
    assert len(payload["report_id"]) == 8


@pytest.mark.asyncio
async def test_report_config_diff_swallows_dispatch_errors():
    tool = ToolsNodes()._build_diff_report_tool()
    with patch("apps.opspilot.metis.llm.chain.node.dispatch_custom_event", side_effect=RuntimeError("no graph")):
        result = await tool.coroutine(title="对比", cluster_name="c1", items=ITEMS)
    assert result == "已生成配置修复对比报告（1 个工作负载），用户可点击查看详细对比。"
