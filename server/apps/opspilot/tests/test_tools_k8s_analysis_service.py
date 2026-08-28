"""Kubernetes 配置分析工具：配额、网络策略、下一步提示、问题工作负载聚合。

mock kube API 边界，断言 JSON 结构与 fail-closed 错误包装。
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client import ApiException

from apps.opspilot.metis.llm.tools.kubernetes import analysis as a


def _items(lst):
    return SimpleNamespace(items=lst)


@pytest.fixture
def core():
    c = MagicMock()
    with patch.object(a, "prepare_context", return_value=None), patch.object(a.client, "CoreV1Api", return_value=c):
        yield c


def test_resource_quotas_computes_percentage_and_wraps_api_error(core):
    quota = SimpleNamespace(
        metadata=SimpleNamespace(name="q1", namespace="prod"),
        status=SimpleNamespace(hard={"cpu": "1000m", "count/pods": "10"}, used={"cpu": "500m", "count/pods": "2"}),
    )
    core.list_resource_quota_for_all_namespaces.return_value = _items([quota])
    with patch.object(a, "parse_resource_quantity", side_effect=lambda v: float(str(v).replace("m", "")) if "m" in str(v) else float(v)):
        out = json.loads(a.check_kubernetes_resource_quotas.invoke({"config": {}}))
    assert out[0]["name"] == "q1"
    assert out[0]["usage_percentage"]["cpu"] == 50.0
    assert out[0]["usage_percentage"]["count/pods"] == 20.0

    core.list_namespaced_resource_quota.side_effect = ApiException(reason="forbidden")
    err = json.loads(a.check_kubernetes_resource_quotas.invoke({"namespace": "prod", "config": {}}))
    assert "error" in err


def test_network_policies_namespaced_and_cluster():
    policy = SimpleNamespace(
        metadata=SimpleNamespace(name="deny-all", namespace="prod"),
        spec=SimpleNamespace(
            pod_selector=SimpleNamespace(match_labels={"app": "web"}),
            policy_types=["Ingress"],
            ingress=[1],
            egress=None,
        ),
    )
    net = MagicMock()
    net.list_network_policy_for_all_namespaces.return_value = _items([policy])
    net.list_namespaced_network_policy.return_value = _items([policy])
    with patch.object(a, "prepare_context"), patch.object(a.client, "NetworkingV1Api", return_value=net):
        all_ns = json.loads(a.check_kubernetes_network_policies.invoke({"config": {}}))
        named = json.loads(a.check_kubernetes_network_policies.invoke({"namespace": "prod", "config": {}}))
        net.list_network_policy_for_all_namespaces.side_effect = ApiException(reason="down")
        err = json.loads(a.check_kubernetes_network_policies.invoke({"config": {}}))
    assert all_ns[0]["ingress_rules"] == 1
    assert named[0]["pod_selector"] == {"app": "web"}
    assert "error" in err


def test_persistent_volumes_join_claims(core):
    pv = SimpleNamespace(
        metadata=SimpleNamespace(name="pv-1"),
        spec=SimpleNamespace(
            capacity={"storage": "10Gi"},
            access_modes=["ReadWriteOnce"],
            persistent_volume_reclaim_policy="Retain",
            storage_class_name="standard",
        ),
        status=SimpleNamespace(phase="Bound"),
    )
    pvc = SimpleNamespace(
        metadata=SimpleNamespace(name="claim-1", namespace="prod"),
        spec=SimpleNamespace(volume_name="pv-1"),
        status=SimpleNamespace(phase="Bound"),
    )
    core.list_persistent_volume.return_value = _items([pv])
    core.list_persistent_volume_claim_for_all_namespaces.return_value = _items([pvc])
    out = json.loads(a.check_kubernetes_persistent_volumes.invoke({"config": {}}))
    assert out[0]["claim"]["name"] == "claim-1"
    assert out[0]["status"] == "Bound"


def test_next_step_hint_and_collect_issue_workloads():
    clean = a.build_config_analysis_next_step_hint(0, target_name="web")
    assert "未发现明显配置问题" in clean
    assert "web" in clean
    assert "request_user_choice" in clean

    many = a.build_config_analysis_next_step_hint(31)
    assert "31 个工作负载" in many
    assert "high/critical" in many
    assert "generate_repair_report" in many

    mapping, workloads = a._collect_issue_workloads(
        [
            {
                "name": "web",
                "namespace": "prod",
                "issues": ["未设置资源限制"],
                "config_analysis": {"containers": [{"issues": ["缺少存活探针"]}]},
            },
            {"name": "ok", "namespace": "prod", "issues": [], "config_analysis": {"containers": []}},
        ]
    )
    assert "web (prod)" in workloads
    assert "ok (prod)" not in workloads
    assert mapping["未设置资源限制"] == ["web (prod)"]
    assert mapping["缺少存活探针"] == ["web (prod)"]


def test_jobs_report_completions_and_api_error():
    job = SimpleNamespace(
        metadata=SimpleNamespace(name="migrate", namespace="prod"),
        spec=SimpleNamespace(completions=1, parallelism=1),
        status=SimpleNamespace(succeeded=1, failed=0, active=0, start_time=None, completion_time=None),
    )
    cron = SimpleNamespace(
        metadata=SimpleNamespace(name="nightly", namespace="prod"),
        spec=SimpleNamespace(schedule="0 1 * * *", suspend=False),
        status=SimpleNamespace(active=[], last_schedule_time=None),
    )
    batch = MagicMock()
    batch.list_job_for_all_namespaces.return_value = _items([job])
    batch.list_cron_job_for_all_namespaces.return_value = _items([cron])
    with patch.object(a, "prepare_context"), patch.object(a.client, "BatchV1Api", return_value=batch):
        out = json.loads(a.check_kubernetes_jobs.invoke({"config": {}}))
    assert out["jobs"][0]["succeeded"] == 1
    assert out["cronjobs"][0]["schedule"] == "0 1 * * *"

    batch.list_job_for_all_namespaces.side_effect = ApiException(reason="down")
    with patch.object(a, "prepare_context"), patch.object(a.client, "BatchV1Api", return_value=batch):
        err = json.loads(a.check_kubernetes_jobs.invoke({"config": {}}))
    assert "error" in err
