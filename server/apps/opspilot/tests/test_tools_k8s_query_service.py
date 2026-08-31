"""Kubernetes 高级查询 @tool 单元测试 (kubernetes/query)。

mock prepare_context(kubeconfig 边界)与 client.*Api,驱动 kubectl_get_resources
分派到各资源 helper;断言别名解析、label/field selector 转发、json/table 输出、
就绪/重启统计、age 计算、外部IP/节点IP 推导、不支持类型与异常包装。
另直接测纯函数 helper(_get_pod_ready_status 等)。不连真实集群。
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pydantic.root_model  # noqa
import pytest

from apps.opspilot.metis.llm.tools.kubernetes import query as q


@pytest.fixture
def apis():
    core, apps = MagicMock(), MagicMock()
    with patch.object(q, "prepare_context", return_value=None), \
         patch.object(q.client, "CoreV1Api", return_value=core), \
         patch.object(q.client, "AppsV1Api", return_value=apps):
        yield core, apps


def _pod(name, phase="Running", statuses=None, ip="1.2.3.4", node="n1", ts=None):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace="default", creation_timestamp=ts),
        status=SimpleNamespace(phase=phase, container_statuses=statuses, pod_ip=ip),
        spec=SimpleNamespace(node_name=node),
    )


# ---------------- pure helpers ----------------
class TestPureHelpers:
    def test_ready_status(self):
        pod = _pod("p", statuses=[SimpleNamespace(ready=True, restart_count=0),
                                  SimpleNamespace(ready=False, restart_count=0)])
        assert q._get_pod_ready_status(pod) == "1/2"

    def test_ready_status_no_containers(self):
        assert q._get_pod_ready_status(_pod("p", statuses=None)) == "0/0"

    def test_restart_count_sum(self):
        pod = _pod("p", statuses=[SimpleNamespace(ready=True, restart_count=2),
                                  SimpleNamespace(ready=True, restart_count=3)])
        assert q._get_pod_restart_count(pod) == 5

    def test_restart_count_none(self):
        assert q._get_pod_restart_count(_pod("p", statuses=None)) == 0

    def test_calculate_age_days_hours_minutes(self):
        now = datetime.now(timezone.utc)
        assert q._calculate_age(now - timedelta(days=3)) == "3d"
        assert q._calculate_age(now - timedelta(hours=5)) == "5h"
        assert q._calculate_age(now - timedelta(minutes=10)).endswith("m")
        assert q._calculate_age(None) == "unknown"

    def test_external_ip_nodeport(self):
        svc = SimpleNamespace(spec=SimpleNamespace(type="NodePort", external_i_ps=None),
                              status=SimpleNamespace(load_balancer=None))
        assert q._get_external_ip(svc) == "<nodes>"

    def test_external_ip_loadbalancer(self):
        ing = SimpleNamespace(ip="9.9.9.9", hostname=None)
        svc = SimpleNamespace(
            spec=SimpleNamespace(type="LoadBalancer", external_i_ps=None),
            status=SimpleNamespace(load_balancer=SimpleNamespace(ingress=[ing])),
        )
        assert q._get_external_ip(svc) == "9.9.9.9"

    def test_node_internal_ip(self):
        node = SimpleNamespace(status=SimpleNamespace(
            addresses=[SimpleNamespace(type="InternalIP", address="10.0.0.5")]))
        assert q._get_node_internal_ip(node) == "10.0.0.5"
        assert q._get_node_external_ip(node) == "<none>"


# ---------------- kubectl_get_resources: pods ----------------
class TestGetPods:
    def test_json_output_with_selectors(self, apis):
        core, _ = apis
        cstat = [SimpleNamespace(ready=True, restart_count=1)]
        core.list_namespaced_pod.return_value = SimpleNamespace(items=[_pod("p1", statuses=cstat)])
        out = json.loads(q.kubectl_get_resources.invoke({
            "resource_type": "po", "namespace": "default",
            "label_selector": "app=nginx", "field_selector": "status.phase=Running", "config": {}}))
        assert out["total"] == 1
        assert out["items"][0]["ready"] == "1/1"
        assert out["items"][0]["restarts"] == 1
        assert out["items"][0]["status"] == "Running"
        core.list_namespaced_pod.assert_called_once_with(
            namespace="default", label_selector="app=nginx", field_selector="status.phase=Running")

    def test_all_namespaces(self, apis):
        core, _ = apis
        core.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[])
        out = json.loads(q.kubectl_get_resources.invoke({"resource_type": "pods", "config": {}}))
        assert out == {"items": [], "total": 0}
        core.list_pod_for_all_namespaces.assert_called_once()

    def test_table_output(self, apis):
        core, _ = apis
        cstat = [SimpleNamespace(ready=True, restart_count=0)]
        core.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[_pod("webpod", statuses=cstat)])
        out = q.kubectl_get_resources.invoke({"resource_type": "pods", "output_format": "table", "config": {}})
        assert "NAME" in out
        assert "webpod" in out


# ---------------- kubectl_get_resources: deployments / nodes / namespaces ----------------
class TestOtherResources:
    def test_deployments_alias(self, apis):
        _, apps = apis
        dep = SimpleNamespace(
            metadata=SimpleNamespace(name="d", namespace="default", creation_timestamp=None),
            spec=SimpleNamespace(replicas=2),
            status=SimpleNamespace(ready_replicas=2, updated_replicas=2, available_replicas=2),
        )
        apps.list_deployment_for_all_namespaces.return_value = SimpleNamespace(items=[dep])
        out = json.loads(q.kubectl_get_resources.invoke({"resource_type": "deploy", "config": {}}))
        assert out["total"] == 1
        assert out["items"][0]["ready"] == "2/2"

    def test_nodes(self, apis):
        core, _ = apis
        node = SimpleNamespace(
            metadata=SimpleNamespace(name="n1", creation_timestamp=None, labels={}),
            status=SimpleNamespace(
                conditions=[SimpleNamespace(type="Ready", status="True")],
                addresses=[SimpleNamespace(type="InternalIP", address="10.0.0.1")],
                node_info=SimpleNamespace(kubelet_version="v1.28"),
            ),
        )
        core.list_node.return_value = SimpleNamespace(items=[node])
        out = json.loads(q.kubectl_get_resources.invoke({"resource_type": "no", "config": {}}))
        assert out["total"] == 1

    def test_namespaces(self, apis):
        core, _ = apis
        ns = SimpleNamespace(
            metadata=SimpleNamespace(name="default", creation_timestamp=None),
            status=SimpleNamespace(phase="Active"),
        )
        core.list_namespace.return_value = SimpleNamespace(items=[ns])
        out = json.loads(q.kubectl_get_resources.invoke({"resource_type": "ns", "config": {}}))
        assert out["total"] == 1


# ---------------- dispatcher edges ----------------
class TestDispatcherEdges:
    def test_unsupported_type(self, apis):
        out = json.loads(q.kubectl_get_resources.invoke({"resource_type": "widgets", "config": {}}))
        assert "暂不支持的资源类型" in out["error"]
        assert "pods" in out["supported_types"]

    def test_exception_wrapped(self, apis):
        core, _ = apis
        core.list_pod_for_all_namespaces.side_effect = RuntimeError("api down")
        out = json.loads(q.kubectl_get_resources.invoke({"resource_type": "pods", "config": {}}))
        assert "查询资源失败" in out["error"]
        assert out["resource_type"] == "pods"


def _meta(name, ns="prod"):
    return SimpleNamespace(name=name, namespace=ns, creation_timestamp=None, labels={})


class TestRemainingResources:
    def test_services_json_and_table(self, apis):
        core, _ = apis
        svc = SimpleNamespace(
            metadata=_meta("web"),
            spec=SimpleNamespace(
                type="NodePort",
                cluster_ip="10.0.0.9",
                ports=[SimpleNamespace(port=80, target_port=8080, protocol="UDP", node_port=30080)],
                external_i_ps=None,
            ),
            status=SimpleNamespace(load_balancer=None),
        )
        core.list_namespaced_service.return_value = SimpleNamespace(items=[svc])
        js = json.loads(q.kubectl_get_resources.invoke({"resource_type": "svc", "namespace": "prod", "config": {}}))
        assert js["items"][0]["ports"] == ["80:8080/UDP"]
        assert js["items"][0]["external_ip"] == "<nodes>"
        table = q.kubectl_get_resources.invoke({"resource_type": "svc", "namespace": "prod", "output_format": "table", "config": {}})
        assert "CLUSTER-IP" in table and "web" in table

    def test_nodes_table_roles_and_not_ready(self, apis):
        core, _ = apis
        node = SimpleNamespace(
            metadata=SimpleNamespace(name="n1", creation_timestamp=None, labels={"node-role.kubernetes.io/control-plane": ""}),
            status=SimpleNamespace(
                conditions=[SimpleNamespace(type="Ready", status="False")],
                addresses=[SimpleNamespace(type="InternalIP", address="10.0.0.1")],
                node_info=SimpleNamespace(kubelet_version="v1.29"),
            ),
        )
        core.list_node.return_value = SimpleNamespace(items=[node])
        js = json.loads(q.kubectl_get_resources.invoke({"resource_type": "nodes", "config": {}}))
        assert js["items"][0]["status"] == "NotReady"
        assert "control-plane" in js["items"][0]["roles"]
        table = q.kubectl_get_resources.invoke({"resource_type": "no", "output_format": "table", "config": {}})
        assert "NotReady" in table and "control-plane" in table

    def test_configmaps_secrets_pv_pvc_events(self, apis):
        core, _ = apis
        cm = SimpleNamespace(metadata=_meta("cfg"), data={"a": "1", "b": "2"})
        secret = SimpleNamespace(metadata=_meta("tok"), data={"k": "v"}, type="Opaque")
        pv = SimpleNamespace(
            metadata=SimpleNamespace(name="pv1", creation_timestamp=None),
            spec=SimpleNamespace(
                capacity={"storage": "10Gi"},
                access_modes=["ReadWriteOnce"],
                persistent_volume_reclaim_policy="Retain",
                storage_class_name="fast",
                claim_ref=SimpleNamespace(namespace="prod", name="pvc1"),
            ),
            status=SimpleNamespace(phase="Bound"),
        )
        pvc = SimpleNamespace(
            metadata=_meta("pvc1"),
            spec=SimpleNamespace(volume_name="pv1", access_modes=["ReadWriteOnce"], storage_class_name="fast"),
            status=SimpleNamespace(phase="Bound", capacity={"storage": "10Gi"}),
        )
        ev = SimpleNamespace(
            metadata=_meta("ev1"),
            type="Warning",
            reason="BackOff",
            message="crash",
            source=SimpleNamespace(component="kubelet"),
            first_timestamp=None,
            last_timestamp=None,
            count=3,
        )
        core.list_config_map_for_all_namespaces.return_value = SimpleNamespace(items=[cm])
        core.list_secret_for_all_namespaces.return_value = SimpleNamespace(items=[secret])
        core.list_persistent_volume.return_value = SimpleNamespace(items=[pv])
        core.list_persistent_volume_claim_for_all_namespaces.return_value = SimpleNamespace(items=[pvc])
        core.list_event_for_all_namespaces.return_value = SimpleNamespace(items=[ev])

        cms = json.loads(q.kubectl_get_resources.invoke({"resource_type": "cm", "config": {}}))
        assert cms["items"][0]["data_keys"] == 2
        secrets = json.loads(q.kubectl_get_resources.invoke({"resource_type": "secrets", "config": {}}))
        assert secrets["items"][0]["type"] == "Opaque"
        assert secrets["items"][0]["data_keys"] == 1
        assert "v" not in secrets["items"][0]
        pvs = json.loads(q.kubectl_get_resources.invoke({"resource_type": "pv", "config": {}}))
        assert pvs["items"][0]["claim"] == "prod/pvc1"
        pvcs = json.loads(q.kubectl_get_resources.invoke({"resource_type": "pvc", "config": {}}))
        assert pvcs["items"][0]["volume"] == "pv1"
        events = json.loads(q.kubectl_get_resources.invoke({"resource_type": "event", "config": {}}))
        assert events["items"][0]["reason"] == "BackOff"
        assert events["items"][0]["count"] == 3

    def test_workloads_rs_ds_sts(self, apis):
        _, apps = apis
        rs = SimpleNamespace(
            metadata=_meta("web-rs"),
            spec=SimpleNamespace(replicas=3),
            status=SimpleNamespace(replicas=3, ready_replicas=2),
        )
        ds = SimpleNamespace(
            metadata=_meta("agent"),
            status=SimpleNamespace(
                desired_number_scheduled=4,
                current_number_scheduled=4,
                number_ready=3,
                updated_number_scheduled=4,
                number_available=3,
            ),
        )
        sts = SimpleNamespace(
            metadata=_meta("db"),
            spec=SimpleNamespace(replicas=2),
            status=SimpleNamespace(ready_replicas=1),
        )
        apps.list_replica_set_for_all_namespaces.return_value = SimpleNamespace(items=[rs])
        apps.list_daemon_set_for_all_namespaces.return_value = SimpleNamespace(items=[ds])
        apps.list_stateful_set_for_all_namespaces.return_value = SimpleNamespace(items=[sts])
        assert json.loads(q.kubectl_get_resources.invoke({"resource_type": "rs", "config": {}}))["items"][0]["ready"] == 2
        assert json.loads(q.kubectl_get_resources.invoke({"resource_type": "ds", "config": {}}))["items"][0]["desired"] == 4
        assert json.loads(q.kubectl_get_resources.invoke({"resource_type": "sts", "config": {}}))["items"][0]["ready"] == "1/2"

    def test_get_all_resources_aggregates_counts(self, apis):
        core, apps = apis
        empty = SimpleNamespace(items=[])
        core.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[_pod("p")])
        core.list_service_for_all_namespaces.return_value = empty
        apps.list_deployment_for_all_namespaces.return_value = empty
        apps.list_replica_set_for_all_namespaces.return_value = empty
        apps.list_daemon_set_for_all_namespaces.return_value = empty
        apps.list_stateful_set_for_all_namespaces.return_value = empty
        core.list_config_map_for_all_namespaces.return_value = empty
        core.list_secret_for_all_namespaces.return_value = empty
        out = json.loads(q.kubectl_get_all_resources.invoke({"config": {}}))
        assert out["resources"]["pods"]["count"] == 1
        assert out["resources"]["services"]["count"] == 0

    def test_deployments_table(self, apis):
        _, apps = apis
        dep = SimpleNamespace(
            metadata=_meta("api"),
            spec=SimpleNamespace(replicas=2),
            status=SimpleNamespace(ready_replicas=2, updated_replicas=2, available_replicas=2),
        )
        apps.list_deployment_for_all_namespaces.return_value = SimpleNamespace(items=[dep])
        table = q.kubectl_get_resources.invoke({"resource_type": "deploy", "output_format": "table", "config": {}})
        assert "UP-TO-DATE" in table and "api" in table

