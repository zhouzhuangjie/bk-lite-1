"""采集任务拓扑参数校验：默认协议、非法协议、回退策略与置信度边界。"""
import pytest
from rest_framework.exceptions import ValidationError

from apps.cmdb.models.collect_model import (
    ALLOWED_TOPOLOGY_FALLBACK_STRATEGIES,
    ALLOWED_TOPOLOGY_PROTOCOLS,
    DEFAULT_TOPOLOGY_FALLBACK_STRATEGY,
    DEFAULT_TOPOLOGY_PROTOCOLS,
)
from apps.cmdb.serializers.collect_serializer import CollectModelSerializer

pytestmark = pytest.mark.unit


def test_missing_protocols_fills_defaults_and_dedupes():
    params = CollectModelSerializer._validate_topology_params({})
    assert params["topology_protocols"] == list(DEFAULT_TOPOLOGY_PROTOCOLS)
    assert params["topology_fallback_strategy"] == DEFAULT_TOPOLOGY_FALLBACK_STRATEGY
    assert params["min_confidence"] == 0.0

    deduped = CollectModelSerializer._validate_topology_params(
        {"topology_protocols": ["lldp", "lldp", "cdp"]}
    )
    assert deduped["topology_protocols"] == ["lldp", "cdp"]


def test_rejects_non_list_and_unknown_protocols():
    with pytest.raises(ValidationError) as err:
        CollectModelSerializer._validate_topology_params({"topology_protocols": "lldp"})
    assert "topology_protocols" in err.value.detail["params"]

    with pytest.raises(ValidationError) as err:
        CollectModelSerializer._validate_topology_params({"topology_protocols": ["ospf"]})
    message = str(err.value.detail["params"]["topology_protocols"])
    for protocol in ALLOWED_TOPOLOGY_PROTOCOLS:
        assert protocol in message


def test_rejects_invalid_fallback_and_confidence():
    with pytest.raises(ValidationError) as err:
        CollectModelSerializer._validate_topology_params({"topology_fallback_strategy": "guess"})
    assert "拓扑回退策略不合法" in str(err.value.detail["params"]["topology_fallback_strategy"])
    assert ALLOWED_TOPOLOGY_FALLBACK_STRATEGIES

    with pytest.raises(ValidationError) as err:
        CollectModelSerializer._validate_topology_params({"min_confidence": "bad"})
    assert "0 到 1" in str(err.value.detail["params"]["min_confidence"])

    with pytest.raises(ValidationError) as err:
        CollectModelSerializer._validate_topology_params({"min_confidence": 1.5})
    assert "0 到 1" in str(err.value.detail["params"]["min_confidence"])

    ok = CollectModelSerializer._validate_topology_params(
        {
            "topology_protocols": ["arp"],
            "topology_fallback_strategy": "strict_neighbors_only",
            "min_confidence": "0.4",
        }
    )
    assert ok["topology_protocols"] == ["arp"]
    assert ok["topology_fallback_strategy"] == "strict_neighbors_only"
    assert ok["min_confidence"] == 0.4
