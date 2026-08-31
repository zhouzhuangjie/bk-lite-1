"""K8S 批量修复报告工具特征测试（行为锁定，重构前基线）。

被测对象：``node.ToolsNodes._build_bulk_repair_tool`` 返回的 ``generate_repair_report``
工具。该方法 ~638 行、内嵌十余个闭包纯函数（_categorize_issue / _severity_for_issue /
_fix_command_for_issue / _auto_generate_items_from_cache / _generate_repair_report …），
是 complexity review 标记的高风险重构点，规划中要整体迁出到
``metis/llm/tools/kubernetes/repair_report.py``。

闭包函数无法在抽出前单独 import，故在**工具 I/O 边界**做特征测试：
给定分析缓存 → 调用工具 → 断言返回文案、以及通过 ``dispatch_custom_event``
派发的 ``config_diff_report`` / ``repair_commands`` 事件。这样能在不改动源码的前提下
锁住 issue→严重级别/修复命令的映射、自动生成、target_names 过滤与分组聚合行为。
"""

import sys
import types

# node.py 间接依赖重型可选驱动模块，测试环境用空 stub 顶替（与 react_agent/cases 一致）。
for _mod_name in ("oracledb", "pyodbc"):
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))

_falkordb = types.ModuleType("falkordb")
_falkordb.Graph = type("Graph", (), {})
sys.modules.setdefault("falkordb", _falkordb)

_falkordb_asyncio = types.ModuleType("falkordb.asyncio")
_falkordb_asyncio.FalkorDB = type("FalkorDB", (), {})
sys.modules.setdefault("falkordb.asyncio", _falkordb_asyncio)

from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402

from apps.opspilot.metis.llm.chain.node import ToolsNodes  # noqa: E402


def _cache_two_deployments():
    """两个 deployment，各一个 issue：payment 缺资源限制（high）、auth 以 root 运行（critical）。"""
    return {
        "cluster_name": "test-cluster",
        "deployments": [
            {"name": "payment", "namespace": "prod", "issues": ["未设置资源限制"], "config_analysis": {}},
            {"name": "auth", "namespace": "prod", "issues": ["容器以 root 用户运行"], "config_analysis": {}},
        ],
    }


async def _invoke(cache, **overrides):
    """构建工具并在边界调用，返回 (返回文案, {事件名: payload})。

    patch 掉 ``dispatch_custom_event`` 以捕获派发事件（同时避免在非 graph 运行
    上下文中调用时抛错）。
    """
    tool = ToolsNodes()._build_bulk_repair_tool(_analysis_cache=cache)
    captured = []

    def _capture(name, payload, *args, **kwargs):
        captured.append((name, payload))

    params = dict(
        title="K8S 配置修复对比",
        context_name="",
        items=[],
        group_by="target",
        expected_target_count=0,
        target_names=[],
    )
    params.update(overrides)

    with patch("apps.opspilot.metis.llm.chain.node.dispatch_custom_event", _capture):
        result = await tool.coroutine(**params)
    return result, dict(captured)


@pytest.mark.asyncio
class TestAutoGenerateFromCache:
    """items 为空时从分析缓存自动生成修复项。"""

    async def test_auto_generates_one_item_per_issue(self):
        """假设缓存有 2 个 deployment 各 1 个 issue；当 items 留空调用；那么返回"共 2 项修复"。"""
        result, _ = await _invoke(_cache_two_deployments(), expected_target_count=2)
        assert "已生成修复对比报告" in result
        assert "共 2 项修复" in result

    async def test_severity_mapping_root_critical_resource_high(self):
        """root issue ⇒ severity=critical，资源限制 issue ⇒ severity=high（按目标聚合后体现在 diff 项上）。"""
        _, events = await _invoke(_cache_two_deployments(), expected_target_count=2)
        report = events["config_diff_report"]
        by_name = {item["workload_name"]: item for item in report["items"]}
        assert by_name["auth"]["severity"] == "critical"
        assert by_name["payment"]["severity"] == "high"

    async def test_fix_commands_dispatched_per_issue(self):
        """为每个 issue 生成 kubectl patch 修复命令，并通过 repair_commands 事件派发。"""
        _, events = await _invoke(_cache_two_deployments(), expected_target_count=2)
        assert "repair_commands" in events
        commands_md = events["repair_commands"]["commands_markdown"]
        assert "kubectl patch deployment payment" in commands_md
        assert "kubectl patch deployment auth" in commands_md


@pytest.mark.asyncio
class TestTargetNamesFilter:
    """target_names 作为范围过滤器，只保留指定目标。"""

    async def test_filter_keeps_only_named_targets(self):
        """假设 target_names=['payment']；当调用工具；那么只剩 payment（共 1 项修复），不含 auth。"""
        result, events = await _invoke(_cache_two_deployments(), target_names=["payment"], expected_target_count=1)
        assert "共 1 项修复" in result
        report = events["config_diff_report"]
        names = {item["workload_name"] for item in report["items"]}
        assert names == {"payment"}


def _cache_probe_and_replica_issues():
    return {
        "cluster_name": "prod-cluster",
        "deployments": [
            {"name": "api", "namespace": "prod", "issues": ["未配置存活探针", "未配置就绪探针"], "config_analysis": {}},
            {"name": "web", "namespace": "prod", "issues": ["使用 latest 标签", "单副本存在单点风险"], "config_analysis": {}},
        ],
    }


@pytest.mark.asyncio
class TestProbeAndReplicaFixCommands:
    async def test_probe_and_replica_issues_generate_kubectl_commands(self):
        result, events = await _invoke(_cache_probe_and_replica_issues(), expected_target_count=2)
        assert "已生成修复对比报告" in result
        commands = events["repair_commands"]["commands_markdown"]
        assert "livenessProbe" in commands or "healthz" in commands
        assert "readinessProbe" in commands or "/ready" in commands
        assert "kubectl scale" in commands or "replicas" in commands
        assert "set image" in commands or "latest" in commands.lower() or "<specific-tag>" in commands


def _cache_container_and_request_issues():
    return {
        "cluster_name": "cache-cluster",
        "deployments": [
            {
                "name": "pay",
                "namespace": "prod",
                "issues": [],
                "config_analysis": {
                    "containers": [
                        {"name": "pay", "issues": ["未设置资源请求", "资源配置不足"]},
                    ]
                },
            },
            {
                "name": "healthy",
                "namespace": "prod",
                "issues": [],
                "config_analysis": {"containers": [{"name": "healthy", "issues": []}]},
            },
        ],
    }


@pytest.mark.asyncio
class TestEmptyItemsAndCacheFill:
    async def test_empty_items_and_empty_cache_returns_no_items(self):
        result, events = await _invoke({"deployments": []}, items=[])
        assert result == "未提供任何修复项。"
        assert "config_diff_report" not in events

    async def test_container_issues_and_resource_request_commands(self):
        result, events = await _invoke(_cache_container_and_request_issues(), expected_target_count=1)
        assert "共 2 项修复" in result
        report = events["config_diff_report"]
        names = {item["workload_name"] for item in report["items"]}
        assert names == {"pay"}
        commands = events["repair_commands"]["commands_markdown"]
        assert "requests" in commands
        assert "kubectl patch deployment pay" in commands

    async def test_incomplete_items_are_merged_from_cache(self):
        items = [
            {
                "target_name": "payment",
                "namespace": "prod",
                "summary": "未设置资源限制",
                "severity": "高危",
                "fix_command": "kubectl patch deployment payment -n prod --type=strategic -p '{\"spec\":{}}'",
            }
        ]
        result, events = await _invoke(
            _cache_two_deployments(),
            items=items,
            expected_target_count=2,
            context_name="",
        )
        assert "共 2 项修复" in result
        report = events["config_diff_report"]
        names = {item["workload_name"] for item in report["items"]}
        assert names == {"payment", "auth"}
        assert events["config_diff_report"]["cluster_name"] == "test-cluster"

    async def test_provided_items_keep_context_from_cache(self):
        items = [
            {
                "target_name": "only",
                "namespace": "ns",
                "summary": "镜像使用 latest 标签",
                "severity": "警告",
                "before": "image: x:latest",
                "after": "image: x:1.0",
                "fix_command": (
                    "# 请手动更新镜像标签为具体版本\n"
                    "kubectl set image deployment/only -n ns only=<image>:<specific-tag>"
                ),
            }
        ]
        result, events = await _invoke(
            {"cluster_name": "from-cache", "deployments": []},
            items=items,
            expected_target_count=1,
            context_name="",
        )
        assert "共 1 项修复" in result
        assert events["config_diff_report"]["cluster_name"] == "from-cache"

    async def test_pydantic_item_and_chinese_severity_and_coverage_note(self):
        tool = ToolsNodes()._build_bulk_repair_tool(_analysis_cache={"cluster_name": "c1"})
        item_cls = tool.args_schema.model_fields["items"].annotation.__args__[0]
        item = item_cls(
            target_name="api",
            namespace="prod",
            summary="配置优化项",
            severity="提示",
            category="配置优化",
        )
        result, events = await _invoke(
            {"cluster_name": "c1", "deployments": []},
            items=[item],
            expected_target_count=3,
            group_by="target",
        )
        assert "注意：本报告覆盖了 1/3 个有问题的目标" in result
        report = events["config_diff_report"]
        assert report["items"][0]["severity"] == "info"
        assert "# (当前配置存在问题)" in report["items"][0]["before_yaml"]

    async def test_group_by_category_and_all(self):
        items = [
            {
                "target_name": "a",
                "namespace": "ns1",
                "target_type": "Deployment",
                "category": "资源配置",
                "summary": "未设置资源限制",
                "severity": "high",
                "fix_command": (
                    "kubectl patch deployment a -n ns1 --type=strategic -p "
                    '\'{"spec":{"template":{"spec":{"containers":[{"name":"a","resources":{"limits":{"cpu":"500m"}}}]}}}}\''
                ),
            },
            {
                "target_name": "b",
                "namespace": "ns2",
                "target_type": "Deployment",
                "category": "资源配置",
                "summary": "未设置资源限制",
                "severity": "high",
                "fix_command": (
                    "kubectl patch deployment b -n ns2 --type=strategic -p "
                    '\'{"spec":{"template":{"spec":{"containers":[{"name":"b","resources":{"limits":{"cpu":"500m"}}}]}}}}\''
                ),
            },
        ]
        result, events = await _invoke({}, items=items, group_by="category")
        assert "共 2 项修复" in result
        cat_item = events["config_diff_report"]["items"][0]
        assert cat_item["workload_type"] == "Multiple"
        assert "资源配置" in cat_item["summary"]
        commands = events["repair_commands"]["commands_markdown"]
        assert "PATCH=" in commands

        result_all, events_all = await _invoke({}, items=items, group_by="all")
        assert "全部（2 个目标）" in events_all["config_diff_report"]["items"][0]["workload_name"]
        assert events_all["config_diff_report"]["items"][0]["workload_type"] == "All"

    async def test_batch_scale_and_image_commands_same_namespace(self):
        items = [
            {
                "target_name": "web1",
                "namespace": "prod",
                "summary": "单副本存在单点风险",
                "severity": "high",
                "fix_command": "kubectl scale deployment web1 -n prod --replicas=3",
            },
            {
                "target_name": "web2",
                "namespace": "prod",
                "summary": "单副本存在单点风险",
                "severity": "high",
                "fix_command": "kubectl scale deployment web2 -n prod --replicas=3",
            },
            {
                "target_name": "img1",
                "namespace": "prod",
                "summary": "使用 latest 标签",
                "severity": "warning",
                "fix_command": "# 请手动更新镜像标签为具体版本\nkubectl set image deployment/img1 -n prod img1=x:1",
            },
            {
                "target_name": "img2",
                "namespace": "prod",
                "summary": "使用 latest 标签",
                "severity": "warning",
                "fix_command": "# 请手动更新镜像标签为具体版本\nkubectl set image deployment/img2 -n prod img2=x:1",
            },
            {
                "target_name": "empty",
                "namespace": "prod",
                "summary": "无命令项",
                "severity": "info",
                "fix_command": "",
            },
        ]
        result, events = await _invoke({}, items=items, group_by="target")
        commands = events["repair_commands"]["commands_markdown"]
        assert "for dep in web1 web2" in commands
        assert "kubectl scale deployment $dep" in commands
        assert "请为以下工作负载更新镜像标签" in commands
        assert "empty" not in commands
        assert "修复命令已直接展示给用户" in result

    async def test_dispatch_and_docx_failures_do_not_block_report(self, monkeypatch):
        import asyncio

        async def boom_wait(*a, **k):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(
            "apps.opspilot.metis.llm.chain.node.asyncio.wait_for",
            boom_wait,
        )
        captured = []

        def _capture(name, payload, *args, **kwargs):
            if name == "config_diff_report":
                raise RuntimeError("dispatch-fail")
            if name == "repair_commands":
                raise RuntimeError("cmd-fail")
            captured.append((name, payload))

        tool = ToolsNodes()._build_bulk_repair_tool(_analysis_cache=_cache_two_deployments())
        with patch("apps.opspilot.metis.llm.chain.node.dispatch_custom_event", _capture):
            result = await tool.coroutine(
                title="t",
                context_name="",
                items=[],
                group_by="target",
                expected_target_count=2,
                target_names=[],
            )
        assert "已生成修复对比报告" in result
        assert "共 2 项修复" in result
