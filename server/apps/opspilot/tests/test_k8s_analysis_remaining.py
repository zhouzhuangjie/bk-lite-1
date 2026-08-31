"""Kubernetes 分析剩余：Ingress hostname、命名空间查询、CronJob 回退、Endpoints 与 HPA。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client import ApiException

from apps.opspilot.metis.llm.tools.kubernetes import analysis as a

pytestmark = pytest.mark.unit


def _items(lst):
    return SimpleNamespace(items=lst)


def test_ingress_hostname_lb_namespaced_and_api_error():
    ingress = SimpleNamespace(
        metadata=SimpleNamespace(name="web", namespace="prod"),
        spec=SimpleNamespace(ingress_class_name="nginx", tls=None, rules=[]),
        status=SimpleNamespace(
            load_balancer=SimpleNamespace(ingress=[SimpleNamespace(ip=None, hostname="lb.example")])
        ),
    )
    net = MagicMock()
    net.list_namespaced_ingress.return_value = _items([ingress])
    net.list_ingress_for_all_namespaces.side_effect = ApiException(reason="forbidden")
    with patch.object(a, "prepare_context"), patch.object(a.client, "NetworkingV1Api", return_value=net):
        named = json.loads(a.check_kubernetes_ingress.invoke({"namespace": "prod", "config": {}}))
        err = json.loads(a.check_kubernetes_ingress.invoke({"config": {}}))
    assert named[0]["load_balancers"] == [{"type": "hostname", "value": "lb.example"}]
    assert "error" in err


def test_daemonset_and_statefulset_instance_name_and_api_errors():
    apps = MagicMock()
    apps.list_namespaced_daemon_set.return_value = _items([])
    apps.list_namespaced_stateful_set.return_value = _items([])
    with (
        patch.object(a, "prepare_context") as prepared,
        patch.object(a.client, "AppsV1Api", return_value=apps),
        patch.object(a, "get_current_cluster_name", return_value="c1"),
    ):
        daemon = json.loads(
            a.check_kubernetes_daemonsets.func(namespace="prod", instance_name="k8s-a", config={"configurable": {}})
        )
        stateful = json.loads(
            a.check_kubernetes_statefulsets.func(namespace="prod", instance_name="k8s-a", config={"configurable": {}})
        )
        apps.list_namespaced_daemon_set.side_effect = ApiException(reason="down")
        apps.list_namespaced_stateful_set.side_effect = ApiException(reason="down")
        daemon_err = json.loads(a.check_kubernetes_daemonsets.func(namespace="prod", config={"configurable": {}}))
        stateful_err = json.loads(a.check_kubernetes_statefulsets.func(namespace="prod", config={"configurable": {}}))
    assert daemon["cluster_name"] == "c1"
    assert stateful["cluster_name"] == "c1"
    written_configs = [call.args[0] for call in prepared.call_args_list if call.args]
    assert any(cfg.get("configurable", {}).get("instance_name") == "k8s-a" for cfg in written_configs)
    assert "error" in daemon_err
    assert "error" in stateful_err


def test_jobs_namespaced_cronjob_attribute_error_falls_back_to_note():
    job = SimpleNamespace(
        metadata=SimpleNamespace(name="migrate", namespace="prod"),
        spec=SimpleNamespace(completions=1, parallelism=1),
        status=SimpleNamespace(succeeded=1, failed=0, active=0, start_time=None, completion_time=None),
    )
    batch = MagicMock()
    batch.list_namespaced_job.return_value = _items([job])
    batch.list_namespaced_cron_job.side_effect = AttributeError("no cron")
    with patch.object(a, "prepare_context"), patch.object(a.client, "BatchV1Api", return_value=batch):
        out = json.loads(a.check_kubernetes_jobs.invoke({"namespace": "prod", "config": {}}))
    assert out["jobs"][0]["name"] == "migrate"
    assert out["cronjobs_note"] == "CronJob API不可用于当前Kubernetes版本"


def test_endpoints_ready_not_ready_and_api_error():
    endpoint = SimpleNamespace(
        metadata=SimpleNamespace(name="svc", namespace="prod"),
        subsets=[
            SimpleNamespace(
                addresses=[
                    SimpleNamespace(
                        ip="10.0.0.2",
                        hostname="pod-a",
                        target_ref=SimpleNamespace(kind="Pod", name="web-0"),
                    )
                ],
                not_ready_addresses=[SimpleNamespace(ip="10.0.0.3", hostname=None, target_ref=None)],
                ports=[SimpleNamespace(name="http", port=80, protocol="TCP")],
            )
        ],
    )
    core = MagicMock()
    core.list_namespaced_endpoints.return_value = _items([endpoint])
    core.list_endpoints_for_all_namespaces.side_effect = ApiException(reason="down")
    with patch.object(a, "prepare_context"), patch.object(a.client, "CoreV1Api", return_value=core):
        named = json.loads(a.check_kubernetes_endpoints.invoke({"namespace": "prod", "config": {}}))
        err = json.loads(a.check_kubernetes_endpoints.invoke({"config": {}}))
    assert named[0]["ready_count"] == 1
    assert named[0]["ready_addresses"][0]["target_ref"] == "Pod/web-0"
    assert named[0]["not_ready_count"] == 1
    assert "error" in err


def test_hpa_namespaced_metrics_and_api_error():
    hpa = SimpleNamespace(
        metadata=SimpleNamespace(name="web", namespace="prod"),
        spec=SimpleNamespace(
            min_replicas=1,
            max_replicas=5,
            scale_target_ref=SimpleNamespace(kind="Deployment", name="web"),
            metrics=[
                SimpleNamespace(
                    type="Resource",
                    resource=SimpleNamespace(
                        name="cpu",
                        target=SimpleNamespace(average_value=None, average_utilization=70),
                    ),
                )
            ],
        ),
        status=SimpleNamespace(
            current_replicas=2,
            desired_replicas=3,
            current_metrics=[
                SimpleNamespace(
                    type="Resource",
                    resource=SimpleNamespace(
                        name="cpu",
                        current=SimpleNamespace(average_value=None, average_utilization=80),
                    ),
                )
            ],
            conditions=[SimpleNamespace(type="AbleToScale", status="True", reason="Ready", message="ok")],
        ),
    )
    auto = MagicMock()
    auto.list_namespaced_horizontal_pod_autoscaler.return_value = _items([hpa])
    auto.list_horizontal_pod_autoscaler_for_all_namespaces.side_effect = ApiException(reason="down")
    with patch.object(a, "prepare_context"), patch.object(a.client, "AutoscalingV2Api", return_value=auto):
        named = json.loads(a.check_kubernetes_hpa_status.invoke({"namespace": "prod", "config": {}}))
        err = json.loads(a.check_kubernetes_hpa_status.invoke({"config": {}}))
    assert named[0]["target_ref"] == "Deployment/web"
    assert named[0]["target_metrics"][0]["target_value"] == 70
    assert named[0]["current_metrics"][0]["current_value"] == 80
    assert named[0]["conditions"][0]["type"] == "AbleToScale"
    assert "error" in err
