"""kubectl 风格查询：别名映射、Pod 就绪/重启、年龄、外部 IP。"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.opspilot.metis.llm.tools.kubernetes import query as q

pytestmark = pytest.mark.unit


def test_query_unknown_resource_lists_supported_types():
    with patch.object(q, "prepare_context"):
        out = json.loads(q._query_resources_internal("widgets"))
    assert "暂不支持的资源类型" in out["error"]
    assert "pods" in out["supported_types"]


def test_query_prepare_context_failure_is_wrapped():
    with patch.object(q, "prepare_context", side_effect=RuntimeError("no kubeconfig")):
        out = json.loads(q._query_resources_internal("pods"))
    assert "查询资源失败" in out["error"]
    assert out["resource_type"] == "pods"


def test_pod_ready_restart_and_age():
    empty = SimpleNamespace(status=SimpleNamespace(container_statuses=None))
    assert q._get_pod_ready_status(empty) == "0/0"
    assert q._get_pod_restart_count(empty) == 0

    pod = SimpleNamespace(
        status=SimpleNamespace(
            container_statuses=[
                SimpleNamespace(ready=True, restart_count=2),
                SimpleNamespace(ready=False, restart_count=1),
            ]
        )
    )
    assert q._get_pod_ready_status(pod) == "1/2"
    assert q._get_pod_restart_count(pod) == 3

    assert q._calculate_age(None) == "unknown"
    now = datetime.now(timezone.utc)
    assert q._calculate_age(now - timedelta(days=3)).endswith("d")
    assert q._calculate_age(now - timedelta(hours=5)).endswith("h")
    assert q._calculate_age(now - timedelta(minutes=8)).endswith("m")


def test_external_and_node_ips():
    lb = SimpleNamespace(
        spec=SimpleNamespace(type="LoadBalancer", external_i_ps=None),
        status=SimpleNamespace(load_balancer=SimpleNamespace(ingress=[SimpleNamespace(ip="1.2.3.4", hostname=None)])),
    )
    assert q._get_external_ip(lb) == "1.2.3.4"
    nodeport = SimpleNamespace(
        spec=SimpleNamespace(type="NodePort", external_i_ps=None),
        status=SimpleNamespace(load_balancer=None),
    )
    assert q._get_external_ip(nodeport) == "<nodes>"
    cluster = SimpleNamespace(
        spec=SimpleNamespace(type="ClusterIP", external_i_ps=["10.0.0.9"]),
        status=SimpleNamespace(load_balancer=None),
    )
    assert q._get_external_ip(cluster) == "10.0.0.9"

    node = SimpleNamespace(
        status=SimpleNamespace(
            addresses=[
                SimpleNamespace(type="InternalIP", address="10.0.0.5"),
                SimpleNamespace(type="ExternalIP", address="8.8.8.8"),
            ]
        )
    )
    assert q._get_node_internal_ip(node) == "10.0.0.5"
    assert q._get_node_external_ip(node) == "8.8.8.8"
    assert q._get_node_internal_ip(SimpleNamespace(status=SimpleNamespace(addresses=None))) == "<none>"
