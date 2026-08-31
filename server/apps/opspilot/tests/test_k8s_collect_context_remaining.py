"""K8s 告警采集：node/service/deployment 上下文与多实例编排。"""
import json
from unittest.mock import Mock, patch

import pytest

from apps.opspilot.metis.llm.tools.kubernetes import data_collection as dc

pytestmark = pytest.mark.unit
MOD = "apps.opspilot.metis.llm.tools.kubernetes.data_collection"


def _tool(return_value):
    return Mock(invoke=Mock(return_value=return_value))


def test_collect_node_service_deployment_context_invokes_typed_tools():
    describe = _tool('{"kind": "Node"}')
    events = _tool('{"events": []}')
    diagnose = _tool('{"ok": true}')
    trace = _tool('{"svc": "api"}')
    history = _tool({"revisions": [{"revision": 3}, {"revision": 2}]})
    compare = _tool('{"diff": "ok"}')
    with (
        patch(f"{MOD}.describe_kubernetes_resource", describe),
        patch(f"{MOD}.get_resource_events_timeline", events),
        patch(f"{MOD}.diagnose_node_issues", diagnose),
        patch(f"{MOD}.trace_service_chain", trace),
        patch(f"{MOD}.get_deployment_revision_history", history),
        patch(f"{MOD}.compare_deployment_revisions", compare),
    ):
        node = dc._collect_node_context({"node_name": "n1"}, {"time_window_minutes": 120})
        assert node["resource_snapshot"] == {"kind": "Node"}
        assert node["node_context"] == {"ok": True}
        assert node["pod_logs"] is None
        describe.invoke.assert_called()

        svc = dc._collect_service_context({"namespace": "prod", "service_name": "api"}, {})
        assert svc["service_topology"] == {"svc": "api"}
        assert svc["events_timeline"] is None

        dep = dc._collect_deployment_context(
            {"namespace": "prod", "deployment_name": "web"},
            {"include_change_context": True},
        )
        assert dep["change_context"]["revision_diff"] == {"diff": "ok"}
        compare.invoke.assert_called_once_with(
            {
                "deployment_name": "web",
                "namespace": "prod",
                "revision1": 2,
                "revision2": 3,
            }
        )

        skipped = dc._collect_deployment_context(
            {"namespace": "prod", "resource_name": "web"},
            {"include_change_context": False},
        )
        assert skipped["change_context"] is None


def test_collect_k8s_context_by_target_type_single_and_multi_instance():
    with (
        patch(f"{MOD}._get_target_instances", return_value=[]),
        patch(f"{MOD}._collect_single_instance_context", return_value={"missing_data": ["unsupported_resource_type"]}) as collect,
    ):
        out = json.loads(dc.collect_k8s_context_by_target_type.func({"resource_type": "cronjob"}, {}))
    collect.assert_called_once()
    assert out["missing_data"] == ["unsupported_resource_type"]

    inst = {"id": 1, "name": "c1", "kubeconfig_data": "k"}
    with (
        patch(f"{MOD}._get_target_instances", return_value=[inst]),
        patch(f"{MOD}._collect_single_instance_context", return_value={"ok": True}),
    ):
        one = json.loads(dc.collect_k8s_context_by_target_type.func({"resource_type": "pod"}, {}))
    assert one["ok"] is True
    assert one["instance"] == {"id": 1, "name": "c1"}

    inst2 = {"id": 2, "name": "c2", "kubeconfig_data": "k2"}
    with (
        patch(f"{MOD}._get_target_instances", return_value=[inst, inst2]),
        patch(f"{MOD}._collect_single_instance_context", return_value={"ok": True}),
    ):
        multi = json.loads(dc.collect_k8s_context_by_target_type.func({"resource_type": "pod"}, {}))
    assert multi["mode"] == "multi_instance"
    assert multi["instance_count"] == 2
    assert multi["instances"][1]["instance"]["name"] == "c2"
