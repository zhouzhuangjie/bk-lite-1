"""控制器安装任务守卫：缺任务/包/阶段不匹配时短路，不远程执行。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.node_mgmt.constants.installer import InstallerConstants
from apps.node_mgmt.models import PackageVersion
from apps.node_mgmt.models.cloud_region import CloudRegion
from apps.node_mgmt.models.installer import ControllerTask, ControllerTaskNode
from apps.node_mgmt.tasks import installer as installer_tasks

pytestmark = pytest.mark.django_db


def _region():
    return CloudRegion.objects.create(name="default-region")


def test_install_controller_missing_task_and_package():
    with pytest.raises(BaseAppException, match="Task not found"):
        installer_tasks.install_controller(999999)
    region = _region()
    task = ControllerTask.objects.create(
        cloud_region=region, type="install", status="pending", package_version_id=999999
    )
    with pytest.raises(BaseAppException, match="Package version not found"):
        installer_tasks.install_controller(task.id)


def test_install_controller_marks_running_and_dispatches():
    region = _region()
    pkg = PackageVersion.objects.create(
        type="controller", os="linux", cpu_architecture="x86_64", object="Controller", version="1.0.0", name="ctl.tar.gz"
    )
    task = ControllerTask.objects.create(
        cloud_region=region, type="install", status="pending", package_version_id=pkg.id
    )
    with patch.object(installer_tasks, "_dispatch_or_finalize_controller_task") as dispatch:
        installer_tasks.install_controller(task.id)
    task.refresh_from_db()
    assert task.status == "running"
    dispatch.assert_called_once_with(task.id)


def test_install_controller_for_node_early_returns():
    assert installer_tasks.install_controller_for_node(999999, 1) is None
    region = _region()
    task = ControllerTask.objects.create(cloud_region=region, type="install", status="running", package_version_id=1)
    node = ControllerTaskNode.objects.create(
        task=task,
        ip="10.0.0.1",
        os="linux",
        port=22,
        username="root",
        password="p",
        status="running",
        result={InstallerConstants.EXECUTION_ATTEMPT_KEY: 2},
    )
    assert installer_tasks.install_controller_for_node(node.id, attempt=1) is None
    node.result = {
        InstallerConstants.EXECUTION_ATTEMPT_KEY: 1,
        "execution_phase": "other",
    }
    node.save()
    assert installer_tasks.install_controller_for_node(node.id, attempt=1) is None


def test_install_controller_for_node_missing_package_records_error():
    region = _region()
    task = ControllerTask.objects.create(cloud_region=region, type="install", status="running", package_version_id=999999)
    node = ControllerTaskNode.objects.create(
        task=task,
        ip="10.0.0.2",
        os="linux",
        port=22,
        username="root",
        password="secret",
        status="running",
        result={
            InstallerConstants.EXECUTION_ATTEMPT_KEY: 1,
            "execution_phase": InstallerConstants.EXECUTION_PHASE_BOOTSTRAP_RUNNING,
            "steps": [],
        },
    )
    with patch.object(installer_tasks, "_dispatch_or_finalize_controller_task") as dispatch:
        installer_tasks.install_controller_for_node(node.id, attempt=1)
    node.refresh_from_db()
    steps = (node.result or {}).get("steps") or []
    assert any("Package version not found" in (s.get("message") or "") for s in steps)
    dispatch.assert_called()


def test_converge_connectivity_missing_node_is_noop():
    assert installer_tasks.converge_controller_install_connectivity_for_node("missing-node") is None
