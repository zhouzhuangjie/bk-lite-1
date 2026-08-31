"""CMDB K8s：search_replicas 映射与过期样本短路。"""
from unittest.mock import patch

import pytest

from apps.cmdb.collection.collect_plugin.k8s import CollectK8sMetrics
from apps.cmdb.collection.constants import (
    K8S_DEPLOYMENT_REPLICAS,
    K8S_REPLICASET_REPLICAS,
    K8S_STATEFULSET_REPLICAS,
)

pytestmark = pytest.mark.unit


def test_search_replicas_maps_workload_types_and_skips_stale_then_unknown():
    runner = CollectK8sMetrics(cluster_name="prod", collector_cluster_id="vm-1")
    now = 2_000_000_000
    vm_data = {
        "data": {
            "result": [
                {
                    "metric": {"__name__": K8S_DEPLOYMENT_REPLICAS, "deployment": "web"},
                    "value": [now, "3"],
                },
                {
                    "metric": {"__name__": K8S_STATEFULSET_REPLICAS, "statefulset": "db"},
                    "value": [now, "2"],
                },
                {
                    "metric": {"__name__": K8S_REPLICASET_REPLICAS, "replicaset": "rs-1"},
                    "value": [now, "5"],
                },
                {
                    "metric": {"__name__": "prometheus_kube_unknown_replicas", "foo": "bar"},
                    "value": [now, "9"],
                },
            ]
        }
    }
    with patch("apps.cmdb.collection.collect_plugin.k8s.Collection") as coll:
        coll.return_value.query.return_value = vm_data
        out = runner.search_replicas()
    assert out == {
        "deployment": {"web": "3"},
        "statefulset": {"db": "2"},
        "replicaset": {"rs-1": "5"},
    }

    stale = {
        "data": {
            "result": [
                {
                    "metric": {"__name__": K8S_DEPLOYMENT_REPLICAS, "deployment": "old"},
                    "value": [1, "1"],
                },
                {
                    "metric": {"__name__": K8S_DEPLOYMENT_REPLICAS, "deployment": "fresh"},
                    "value": [now, "4"],
                },
            ]
        }
    }
    with patch("apps.cmdb.collection.collect_plugin.k8s.Collection") as coll:
        coll.return_value.query.return_value = stale
        stale_out = runner.search_replicas()
    assert stale_out == {}
