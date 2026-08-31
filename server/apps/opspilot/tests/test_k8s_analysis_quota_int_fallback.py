"""K8s 配额：整数回退与无法计算。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client import ApiException

from apps.opspilot.metis.llm.tools.kubernetes import analysis as a

pytestmark = pytest.mark.unit


def test_resource_quotas_integer_fallback_and_uncomputable():
    quota = SimpleNamespace(
        metadata=SimpleNamespace(name="q2", namespace="prod"),
        status=SimpleNamespace(
            hard={"count/pods": "10", "weird": "n/a", "zero": "0"},
            used={"count/pods": "4", "weird": "x", "zero": "1"},
        ),
    )
    core = MagicMock()
    core.list_namespaced_resource_quota.return_value = SimpleNamespace(items=[quota])
    with (
        patch.object(a, "prepare_context"),
        patch.object(a.client, "CoreV1Api", return_value=core),
        patch.object(a, "parse_resource_quantity", side_effect=ValueError("not qty")),
    ):
        out = json.loads(a.check_kubernetes_resource_quotas.invoke({"namespace": "prod", "config": {}}))
    usage = out[0]["usage_percentage"]
    assert usage["count/pods"] == 40.0
    assert usage["weird"] == "无法计算"
    assert "zero" not in usage
