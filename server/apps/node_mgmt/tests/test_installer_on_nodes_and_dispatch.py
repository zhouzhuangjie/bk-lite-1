"""控制器安装：缺凭据短路、调度 waiting 节点、任务结束刷新版本。"""
from unittest.mock import patch

import pytest

from apps.core.utils.crypto.aes_crypto import AESCryptor
from apps.node_mgmt.constants.installer import InstallerConstants
from apps.node_mgmt.models import PackageVersion
from apps.node_mgmt.models.cloud_region import CloudRegion
from apps.node_mgmt.models.installer import ControllerTask, ControllerTaskNode
from apps.node_mgmt.tasks import installer as installer_tasks

pytestmark = pytest.mark.django_db


def _region():
    return CloudRegion.objects.create(name="install-region")


def _pkg():
    return PackageVersion.objects.create(
        type="controller",
        os="linux",
        cpu_architecture="x86_64",
        object="Controller",
        version="1.0.0",
        name="ctl.tar.gz",
    )


def test_install_controller_on_nodes_skips_missing_credentials():
    region = _region()
    pkg = _pkg()
    task = ControllerTask.objects.create(cloud_region=region, type="install", status="running", package_version_id=pkg.id)
    node = ControllerTaskNode.objects.create(
        task=task,
        ip="10.0.0.8",
        os="linux",
        port=22,
        username="root",
        password="",
        private_key="",
        status="running",
        result={},
    )
    with patch.object(installer_tasks, "exec_command_to_remote") as remote:
        installer_tasks.install_controller_on_nodes(task, [node], pkg)
    remote.assert_not_called()
    node.refresh_from_db()
    assert node.status == "error"
    steps = (node.result or {}).get("steps") or (node.result or {}).get("step_list") or []
    blob = str(node.result)
    assert "Password or private key is required" in blob or any("credential" in str(s).lower() for s in steps)


def test_install_controller_on_nodes_runs_linux_stream_install():
    region = _region()
    pkg = _pkg()
    task = ControllerTask.objects.create(
        cloud_region=region, type="install", status="running", package_version_id=pkg.id, work_node="jump"
    )
    password = AESCryptor().encode("secret")
    node = ControllerTaskNode.objects.create(
        task=task,
        ip="10.0.0.9",
        os="linux",
        port=22,
        username="root",
        password=password,
        cpu_architecture="x86_64",
        status="running",
        result={},
        organizations=[1],
        node_name="n1",
    )
    with (
        patch.object(installer_tasks, "subscribe_lines_sync", return_value=(object(), lambda: None)),
        patch.object(installer_tasks, "exec_command_to_remote_stream", return_value={"result": "ok"}) as stream,
        patch.object(installer_tasks, "_apply_installer_events_to_node"),
        patch.object(installer_tasks, "_finalize_non_connectivity_running_steps"),
        patch.object(installer_tasks, "_advance_step"),
        patch.object(installer_tasks, "_save_node_pending_connectivity"),
        patch.object(installer_tasks, "_dispatch_or_finalize_controller_task"),
        patch.object(
            installer_tasks.InstallerService,
            "resolve_package_by_architecture",
            return_value=pkg,
        ),
        patch.object(
            installer_tasks.InstallerService,
            "get_install_command",
            return_value="install.sh",
        ),
        patch.object(installer_tasks, "_consume_installer_stream"),
    ):
        installer_tasks.install_controller_on_nodes(task, [node], pkg)
    stream.assert_called_once()
    node.refresh_from_db()
    assert InstallerConstants.INSTALL_NODE_ID_KEY in (node.result or {})


def test_dispatch_or_finalize_marks_waiting_node_and_queues_delay():
    region = _region()
    pkg = _pkg()
    task = ControllerTask.objects.create(cloud_region=region, type="install", status="pending", package_version_id=pkg.id)
    node = ControllerTaskNode.objects.create(
        task=task,
        ip="10.0.0.10",
        os="linux",
        port=22,
        username="root",
        password="p",
        status=InstallerConstants.STEP_STATUS_WAITING,
        result={},
    )
    with (
        patch.object(installer_tasks.transaction, "on_commit", side_effect=lambda fn: fn()),
        patch.object(installer_tasks.install_controller_for_node, "delay") as delay,
    ):
        installer_tasks._dispatch_or_finalize_controller_task(task.id)
    node.refresh_from_db()
    task.refresh_from_db()
    assert node.status == InstallerConstants.STEP_STATUS_RUNNING
    assert (node.result or {}).get(InstallerConstants.EXECUTION_PHASE_KEY) == InstallerConstants.EXECUTION_PHASE_BOOTSTRAP_RUNNING
    assert task.status == "running"
    delay.assert_called_once_with(node.id, (node.result or {}).get(InstallerConstants.EXECUTION_ATTEMPT_KEY))


def test_dispatch_or_finalize_ignores_non_install_task():
    region = _region()
    task = ControllerTask.objects.create(cloud_region=region, type="uninstall", status="pending", package_version_id=1)
    assert installer_tasks._dispatch_or_finalize_controller_task(task.id) is None
    assert installer_tasks._dispatch_or_finalize_controller_task(999999) is None
