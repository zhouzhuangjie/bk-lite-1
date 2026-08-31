"""InstallerViewSet：采集器安装下发与任务节点分页，以及 Windows 安装包下载。"""
import json
import uuid
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.node_mgmt.constants.node import NodeConstants
from apps.node_mgmt.models import CloudRegion, Node
from apps.node_mgmt.models.installer import CollectorTask, CollectorTaskNode
from apps.node_mgmt.models.sidecar import NodeOrganization
from apps.node_mgmt.views.installer import InstallerViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def _user():
    user = UserFactory(username=f"inst-{uuid.uuid4().hex[:8]}", domain="domain.com", is_superuser=True)
    user.locale = "en"
    return user


def _auth(request, user=None):
    user = user or _user()
    force_authenticate(request, user=user)
    request.COOKIES["current_team"] = "1"
    return user


def test_collector_install_authorizes_and_dispatches(monkeypatch):
    monkeypatch.setattr(
        "apps.node_mgmt.views.installer.authorize_node_ids",
        lambda request, node_ids: (node_ids, None),
    )
    install = MagicMock(return_value=77)
    delay = MagicMock()
    monkeypatch.setattr("apps.node_mgmt.views.installer.InstallerService.install_collector", install)
    monkeypatch.setattr("apps.node_mgmt.views.installer.install_collector.delay", delay)
    request = factory.post(
        "/installer/collector/install/",
        {"collector_package": 3, "nodes": [{"node_id": "n1"}, "n2"]},
        format="json",
    )
    _auth(request)
    resp = InstallerViewSet.as_view({"post": "collector_install"})(request)
    body = json.loads(resp.content)
    assert body["result"] is True
    assert body["data"]["task_id"] == 77
    install.assert_called_once_with(3, [{"node_id": "n1"}, "n2"])
    delay.assert_called_once_with(77)


def test_collector_install_returns_authorize_error(monkeypatch):
    from django.http import JsonResponse

    err = JsonResponse({"result": False, "message": "forbidden"}, status=403)
    monkeypatch.setattr(
        "apps.node_mgmt.views.installer.authorize_node_ids",
        lambda request, node_ids: ([], err),
    )
    request = factory.post(
        "/installer/collector/install/",
        {"collector_package": 3, "nodes": [{"node_id": "n1"}]},
        format="json",
    )
    _auth(request)
    resp = InstallerViewSet.as_view({"post": "collector_install"})(request)
    assert resp.status_code == 403
    assert json.loads(resp.content)["result"] is False


def test_collector_install_nodes_filters_status_and_summarizes(monkeypatch):
    region = CloudRegion.objects.create(name=f"cr-{uuid.uuid4().hex[:8]}")
    keep = Node.objects.create(
        id=f"keep-{uuid.uuid4().hex[:8]}",
        name="keep-node",
        ip="10.0.0.1",
        operating_system=NodeConstants.LINUX_OS,
        collector_configuration_directory="/tmp",
        cloud_region=region,
        status={},
    )
    waiting = Node.objects.create(
        id=f"wait-{uuid.uuid4().hex[:8]}",
        name="wait-node",
        ip="10.0.0.2",
        operating_system=NodeConstants.LINUX_OS,
        collector_configuration_directory="/tmp",
        cloud_region=region,
        status={},
    )
    NodeOrganization.objects.create(node=keep, organization=7)
    task = CollectorTask.objects.create(type="install", package_version_id=1, status="running")
    CollectorTaskNode.objects.create(
        task=task,
        node=keep,
        status="success",
        result={"overall_status": "success"},
    )
    CollectorTaskNode.objects.create(task=task, node=waiting, status="waiting", result={})
    monkeypatch.setattr(
        "apps.node_mgmt.views.installer.get_authorized_node_queryset",
        lambda request: Node.objects.filter(id__in=[keep.id, waiting.id]),
    )
    request = factory.post(
        f"/installer/collector/install/{task.id}/nodes/",
        {"status": ["success"], "page": 1, "page_size": 10},
        format="json",
    )
    _auth(request)
    resp = InstallerViewSet.as_view({"post": "collector_install_nodes"})(request, task_id=task.id)
    data = json.loads(resp.content)["data"]
    assert data["task_id"] == task.id
    assert data["status"] == "running"
    assert data["count"] == 1
    assert data["items"][0]["node_id"] == keep.id
    assert data["items"][0]["status"] == "success"
    assert data["items"][0]["ip"] == keep.ip
    assert data["items"][0]["organizations"] == [7]
    assert data["summary"]["total"] == 2
    assert data["summary"]["success"] == 1
    assert data["summary"]["waiting"] == 1


def test_windows_download_returns_artifact(monkeypatch):
    captured = {}

    def fake_download(arch):
        captured["arch"] = arch
        return BytesIO(b"MZ"), "installer.exe"

    monkeypatch.setattr(
        "apps.node_mgmt.views.installer.InstallerService.download_windows_installer",
        fake_download,
    )
    request = factory.get("/installer/windows/download/")
    _auth(request)
    resp = InstallerViewSet.as_view({"get": "windows_download"})(request)
    assert resp.status_code == 200
    assert captured["arch"] == ""
    assert "attachment" in resp["Content-Disposition"]
