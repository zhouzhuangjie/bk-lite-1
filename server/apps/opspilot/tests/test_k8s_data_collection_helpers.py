"""K8s 告警采集纯函数：JSON 解析、证据块、owner/config/service 引用。"""
import json

import pytest

from apps.opspilot.metis.llm.tools.kubernetes import data_collection as dc

pytestmark = pytest.mark.unit


def test_json_or_raw_and_evidence_and_first_non_empty():
    assert dc._json_or_raw({"a": 1}) == {"a": 1}
    assert dc._json_or_raw(None) is None
    assert dc._json_or_raw('{"k": 2}') == {"k": 2}
    assert dc._json_or_raw("not-json") == "not-json"
    assert dc._json_or_raw(3) == 3
    assert dc._evidence_block(error="boom") == {"status": "failed", "data": None, "error": "boom"}
    assert dc._evidence_block() == {"status": "skipped", "data": None, "error": None}
    assert dc._evidence_block({"ok": True}) == {"status": "success", "data": {"ok": True}, "error": None}
    assert dc._evidence_block(1, status="custom")["status"] == "custom"
    assert dc._first_non_empty("", [], {}, None, "x") == "x"
    assert dc._first_non_empty("", None) is None


def test_extract_owner_config_service_and_enrich_pod():
    assert dc._extract_owner_workload("bad") is None
    assert dc._extract_owner_workload({"metadata": {}}) is None
    assert dc._extract_owner_workload(
        {"metadata": {"ownerReferences": [{"kind": "ReplicaSet", "name": "rs-1", "uid": "u1"}]}}
    ) == {"kind": "ReplicaSet", "name": "rs-1", "uid": "u1"}

    snapshot = {
        "metadata": {"ownerReferences": [{"kind": "ReplicaSet", "name": "rs-1", "uid": "u1"}]},
        "spec": {
            "volumes": [
                {"configMap": {"name": "cm1"}, "secret": {"secretName": "s1"}},
                {"configMap": {"name": "cm1"}},
            ],
            "containers": [
                {
                    "envFrom": [{"configMapRef": {"name": "cm2"}}, {"secretRef": {"name": "s2"}}],
                    "env": [
                        {"valueFrom": {"configMapKeyRef": {"name": "cm3"}}},
                        {"valueFrom": {"secretKeyRef": {"name": "s3"}}},
                    ],
                }
            ],
        },
    }
    refs = dc._extract_config_references(snapshot)
    assert refs["config_maps"] == ["cm1", "cm2", "cm3"]
    assert refs["secrets"] == ["s1", "s2", "s3"]
    assert dc._extract_config_references("x") == {"config_maps": [], "secrets": []}

    enriched = dc._enrich_pod_snapshot(snapshot)
    assert enriched["owner_workload"]["name"] == "rs-1"
    assert "cm1" in enriched["config_references"]["config_maps"]
    assert dc._enrich_pod_snapshot("x") == "x"

    assert dc._extract_service_reference_from_logs("ok") is None
    assert dc._extract_service_reference_from_logs("lookup api.prod.svc no such host") == {
        "service_name": "api",
        "namespace": "prod",
    }


def test_collect_single_instance_unsupported_and_configurable():
    assert dc._configurable(None) == {}
    assert dc._configurable({"configurable": {"a": 1}}) == {"a": 1}
    cfg = dc._build_instance_config({"configurable": {"keep": True}}, {"id": "i1", "name": "n1", "kubeconfig_data": "k"})
    assert cfg["configurable"]["instance_id"] == "i1"
    assert cfg["configurable"]["keep"] is True
    payload = dc._collect_single_instance_context({"resource_type": "cronjob"}, {})
    assert payload["missing_data"] == ["unsupported_resource_type"]
    assert dc._extract_labels({"labels": {"app": "x"}}) == {"app": "x"}
    assert dc._extract_labels({"labels": "bad"}) == {}
    out = json.loads(dc.normalize_alert_event.func({"labels": {"alertname": "A"}, "annotations": {"s": "1"}}))
    assert out["labels"]["alertname"] == "A"
    assert json.loads(dc.normalize_alert_event.func("bad"))["labels"] == {}


def test_resolve_k8s_target_from_alert_labels():
    pod = json.loads(dc.resolve_k8s_target_from_alert.func({"labels": {"pod": "p1", "namespace": "ns"}}))
    assert pod["resource_type"] == "pod"
    assert pod["resource_name"] == "p1"
    assert pod["resolved"] is True

    node = json.loads(dc.resolve_k8s_target_from_alert.func({"labels": {"node": "n1"}}))
    assert node["resource_type"] == "node"
    assert node["resolved"] is True

    svc = json.loads(
        dc.resolve_k8s_target_from_alert.func({"labels": {"service": "api", "namespace": "prod"}})
    )
    assert svc["resource_type"] == "service"
    assert svc["resource_name"] == "api"
    assert svc["resolved"] is True

    dep = json.loads(
        dc.resolve_k8s_target_from_alert.func({"labels": {"deployment": "web", "namespace": "prod"}})
    )
    assert dep["resource_type"] == "deployment"
    assert dep["resolved"] is True

    missing = json.loads(dc.resolve_k8s_target_from_alert.func({"labels": {"namespace": "prod"}}))
    assert missing["resolved"] is False
    assert missing["missing_data"] == ["resource_type_or_name"]
    assert missing["reason"] == "Missing resource identifier needed to resolve Kubernetes target"
