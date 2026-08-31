"""跨命名空间搜索工作负载：StatefulSet/DaemonSet 与多实例加载失败。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client import ApiException

from apps.opspilot.metis.llm.tools.kubernetes import resources as res

pytestmark = pytest.mark.unit


def _meta(name, namespace):
    return SimpleNamespace(name=name, namespace=namespace, creation_timestamp=None, labels=None)


def test_search_workload_statefulset_daemonset_and_instance_load_error():
    apps = MagicMock()
    empty = SimpleNamespace(items=[])
    sts = SimpleNamespace(
        metadata=_meta("cache", "prod"),
        spec=SimpleNamespace(replicas=3),
        status=SimpleNamespace(ready_replicas=2),
    )
    ds = SimpleNamespace(
        metadata=_meta("agent", "kube-system"),
        spec=SimpleNamespace(),
        status=SimpleNamespace(desired_number_scheduled=4, number_ready=4),
    )
    apps.list_deployment_for_all_namespaces.return_value = empty
    apps.list_stateful_set_for_all_namespaces.return_value = SimpleNamespace(items=[sts])
    apps.list_daemon_set_for_all_namespaces.return_value = SimpleNamespace(items=[ds])

    with (
        patch.object(res, "prepare_context"),
        patch.object(res.client, "AppsV1Api", return_value=apps),
        patch(
            "apps.opspilot.metis.llm.tools.kubernetes.connection.get_kubernetes_instances_from_configurable",
            return_value=[],
        ),
    ):
        sts_out = json.loads(res.search_workload_across_namespaces.invoke({"workload_name": "cache", "config": {}}))
        ds_out = json.loads(res.search_workload_across_namespaces.invoke({"workload_name": "agent", "config": {}}))
    assert sts_out["locations"][0]["kind"] == "StatefulSet"
    assert sts_out["locations"][0]["replicas"] == 3
    assert sts_out["locations"][0]["ready_replicas"] == 2
    assert ds_out["locations"][0]["kind"] == "DaemonSet"
    assert ds_out["locations"][0]["replicas"] == 4

    apps.list_deployment_for_all_namespaces.side_effect = ApiException(reason="forbidden")
    apps.list_stateful_set_for_all_namespaces.return_value = empty
    apps.list_daemon_set_for_all_namespaces.return_value = empty
    with (
        patch.object(res, "prepare_context"),
        patch.object(res.client, "AppsV1Api", return_value=apps),
        patch(
            "apps.opspilot.metis.llm.tools.kubernetes.connection.get_kubernetes_instances_from_configurable",
            return_value=[{"name": "c1", "kubeconfig_data": "not-yaml"}],
        ),
        patch("apps.opspilot.metis.llm.tools.kubernetes.resources.logger") as logger,
    ):
        bad = json.loads(res.search_workload_across_namespaces.invoke({"workload_name": "x", "config": {}}))
    assert bad["found"] is False
    assert logger.warning.called
