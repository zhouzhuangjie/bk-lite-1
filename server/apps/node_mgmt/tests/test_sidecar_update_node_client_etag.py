"""Sidecar.update_node_client：ETag 命中返回 304 并刷新状态。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.node_mgmt.models import Node
from apps.node_mgmt.models.cloud_region import CloudRegion
from apps.node_mgmt.services.sidecar import Sidecar

pytestmark = pytest.mark.django_db


def test_update_node_client_etag_hit_returns_304_and_updates_status():
    region = CloudRegion.objects.create(name="etag-region")
    node = Node.objects.create(
        id="node-etag-1",
        name="n1",
        ip="10.9.9.9",
        operating_system="linux",
        collector_configuration_directory="/etc/sidecar",
        cloud_region=region,
        status={"ok": True},
    )
    req = SimpleNamespace(
        headers={"If-None-Match": '"etag-abc"'},
        data={"node_details": {"status": {"cpu": 1}, "ip": "10.9.9.9"}},
    )
    with patch("apps.node_mgmt.services.sidecar.cache.get", return_value="etag-abc"), patch.object(
        Sidecar, "trigger_converge_tasks_if_needed"
    ) as converge:
        resp = Sidecar.update_node_client(req, node.id)
    assert resp.status_code == 304
    assert resp["ETag"] == "etag-abc"
    converge.assert_called_once_with(node.id, "10.9.9.9", {"cpu": 1})
    node.refresh_from_db()
    assert node.status == {"cpu": 1}
