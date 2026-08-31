"""节点管理：sidecar 同步、云区域健康检查与内置初始化命令。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from apps.node_mgmt.constants.cloudregion_service import CloudRegionServiceConstants
from apps.node_mgmt.models.cloud_region import CloudRegion, CloudRegionService
from apps.node_mgmt.tasks.cloudregion import check_all_region_services
from apps.node_mgmt.tasks.sidecar_config import sync_node_properties_to_sidecar

pytestmark = pytest.mark.django_db


def test_sync_node_properties_missing_valueerror_and_unexpected():
    assert sync_node_properties_to_sidecar("missing-node") == {"success": False, "error": "Node not found"}

    node = SimpleNamespace(id="n1")
    with (
        patch("apps.node_mgmt.tasks.sidecar_config.Node.objects.get", return_value=node),
        patch(
            "apps.node_mgmt.tasks.sidecar_config.SidecarConfigService.sync_node_properties",
            side_effect=ValueError("bad org"),
        ),
    ):
        assert sync_node_properties_to_sidecar("n1", name="x") == {"success": False, "error": "bad org"}

    with (
        patch("apps.node_mgmt.tasks.sidecar_config.Node.objects.get", return_value=node),
        patch(
            "apps.node_mgmt.tasks.sidecar_config.SidecarConfigService.sync_node_properties",
            side_effect=RuntimeError("io"),
        ),
    ):
        out = sync_node_properties_to_sidecar("n1")
        assert out["success"] is False
        assert out["error"] == "io"

    with (
        patch("apps.node_mgmt.tasks.sidecar_config.Node.objects.get", return_value=node),
        patch("apps.node_mgmt.tasks.sidecar_config.SidecarConfigService.sync_node_properties") as sync,
    ):
        assert sync_node_properties_to_sidecar("n1", organizations=["1"]) == {"success": True}
    sync.assert_called_once_with(node, name=None, organizations=["1"])


def test_check_all_region_services_updates_normal_and_skips_unknown():
    region = CloudRegion.objects.create(name="r-health")
    known = CloudRegionService.objects.create(
        cloud_region=region, name=CloudRegionServiceConstants.STARGAZER_SERVICE_NAME, status="old"
    )
    unknown = CloudRegionService.objects.create(cloud_region=region, name="other", status="old")
    with patch(
        "apps.node_mgmt.tasks.cloudregion.SERVICES_FUNC",
        {CloudRegionServiceConstants.STARGAZER_SERVICE_NAME: lambda r: (CloudRegionServiceConstants.NORMAL, "ok")},
    ):
        check_all_region_services()
    known.refresh_from_db()
    unknown.refresh_from_db()
    assert known.status == CloudRegionServiceConstants.NORMAL
    assert known.deployed_status == CloudRegionServiceConstants.DEPLOYED
    assert known.message == "ok"
    assert unknown.status == "old"


def test_node_init_command_runs_cloud_controller_collector(monkeypatch):
    calls = []
    monkeypatch.setattr("apps.node_mgmt.management.commands.node_init.cloud_init", lambda: calls.append("cloud"))
    monkeypatch.setattr(
        "apps.node_mgmt.management.commands.node_init.controller_init", lambda: calls.append("controller")
    )
    monkeypatch.setattr(
        "apps.node_mgmt.management.commands.node_init.collector_init", lambda: calls.append("collector")
    )
    call_command("node_init")
    assert calls == ["cloud", "controller", "collector"]
