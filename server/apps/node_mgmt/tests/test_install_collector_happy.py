"""install_collector / _install_collector_inner：linux zip 成功路径与未处理异常收口。"""
from unittest.mock import patch

import pytest

from apps.node_mgmt.models import Collector, Node, PackageVersion
from apps.node_mgmt.models.cloud_region import CloudRegion
from apps.node_mgmt.models.installer import CollectorTask, CollectorTaskNode, NodeCollectorInstallStatus
from apps.node_mgmt.tasks import installer as installer_tasks

pytestmark = pytest.mark.django_db


def _setup():
    region = CloudRegion.objects.create(name="col-install")
    node = Node.objects.create(
        id="node-col-1",
        name="n1",
        ip="10.3.3.3",
        operating_system="linux",
        cpu_architecture="x86_64",
        collector_configuration_directory="/etc/sidecar",
        cloud_region=region,
    )
    pkg = PackageVersion.objects.create(
        type="collector",
        os="linux",
        cpu_architecture="x86_64",
        object="Telegraf",
        version="1.0.0",
        name="telegraf.zip",
    )
    collector = Collector.objects.create(
        id="c-telegraf-1",
        name="Telegraf",
        service_type="svc",
        node_operating_system="linux",
        executable_path="/opt/telegraf",
        execute_parameters="-config",
    )
    task = CollectorTask.objects.create(type="install", status="pending", package_version_id=pkg.id)
    task_node = CollectorTaskNode.objects.create(task=task, node=node, status="waiting", result={})
    return task, task_node, pkg, collector, node


def test_install_collector_linux_zip_sets_executable_and_status():
    task, task_node, pkg, collector, node = _setup()
    with (
        patch.object(installer_tasks.PackageService, "resolve_package_by_architecture", return_value=pkg),
        patch.object(installer_tasks.PackageService, "resolve_existing_file_path", return_value="pkgs/telegraf.zip"),
        patch.object(installer_tasks, "download_to_local") as download,
        patch.object(installer_tasks, "unzip_file", return_value="telegraf") as unzip,
        patch.object(installer_tasks, "exec_command_to_local") as exec_local,
        patch.object(
            installer_tasks.PackageService,
            "resolve_collector_by_architecture",
            return_value=collector,
        ),
    ):
        installer_tasks.install_collector(task.id)
    download.assert_called_once()
    unzip.assert_called_once()
    exec_local.assert_called_once()
    task.refresh_from_db()
    task_node.refresh_from_db()
    assert task.status == "finished"
    assert task_node.status == "success"
    assert task_node.result["final_message"] == "Collector installation completed"
    status = NodeCollectorInstallStatus.objects.get(node=node, collector=collector)
    assert status.status == "success"


def test_install_collector_unhandled_exception_marks_waiting_nodes_error():
    task, task_node, *_ = _setup()
    with patch.object(installer_tasks, "_install_collector_inner", side_effect=RuntimeError("boom")):
        installer_tasks.install_collector(task.id)
    task.refresh_from_db()
    task_node.refresh_from_db()
    assert task.status == "finished"
    assert task_node.status == "error"
    assert task_node.result["final_message"] == "Collector installation failed due to an unexpected error"
