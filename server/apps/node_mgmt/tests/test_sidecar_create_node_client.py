"""Sidecar.update_node_client：新建节点、默认配置与动作 ack。"""
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.node_mgmt.constants.controller import ControllerConstants
from apps.node_mgmt.models import Collector, Node
from apps.node_mgmt.models.cloud_region import CloudRegion
from apps.node_mgmt.models.sidecar import CollectorConfiguration
from apps.node_mgmt.services.sidecar import Sidecar

pytestmark = pytest.mark.django_db


def test_update_node_client_creates_node_and_default_config():
    suffix = uuid.uuid4().hex[:8]
    region = CloudRegion.objects.create(name=f"cr-new-{suffix}")
    collector = Collector.objects.create(
        id=f"c-def-{suffix}",
        name=f"Metricbeat-{suffix}",
        service_type="svc",
        node_operating_system="linux",
        executable_path="/bin",
        execute_parameters="-c",
        default_config={"nats": "host: {{ HOST }}"},
    )
    node_id = f"node-new-{suffix}"
    req = SimpleNamespace(
        headers={},
        META={},
        data={
            "node_name": "edge-new",
            "node_details": {
                "ip": "10.4.4.4",
                "operating_system": "Linux",
                "collector_configuration_directory": "/etc/sidecar",
                "metrics": {},
                "status": {"cpu": 1},
                "log_file_list": [],
                "tags": [
                    f"{ControllerConstants.CLOUD_TAG}:{region.id}",
                    f"{ControllerConstants.GROUP_TAG}:1",
                ],
            },
        },
    )
    with (
        patch("apps.node_mgmt.services.sidecar.cache.get", return_value=None),
        patch.object(Sidecar, "_get_default_collectors_for_node", return_value={collector.name: collector}),
        patch.object(Sidecar, "get_cloud_region_envconfig", return_value={"HOST": "10.4.4.4", "SIDECAR_INPUT_MODE": "nats"}),
        patch.object(Sidecar, "asso_groups") as asso,
        patch.object(Sidecar, "trigger_converge_tasks_if_needed"),
        patch("apps.node_mgmt.services.sidecar.cache.set"),
    ):
        resp = Sidecar.update_node_client(req, node_id)
    node = Node.objects.get(id=node_id)
    assert node.ip == "10.4.4.4"
    assert node.operating_system == "linux"
    assert node.cloud_region_id == region.id
    asso.assert_called_once()
    cfg = CollectorConfiguration.objects.get(collector=collector, nodes=node, is_pre=True)
    assert "10.4.4.4" in cfg.config_template
    assert resp.status_code == 202
