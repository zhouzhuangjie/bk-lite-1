"""timeout_controller_install_task：缺任务/非 running/非连通检测阶段短路；超时写 error。"""
import pytest

from apps.node_mgmt.constants.installer import InstallerConstants
from apps.node_mgmt.models import PackageVersion
from apps.node_mgmt.models.cloud_region import CloudRegion
from apps.node_mgmt.models.installer import ControllerTask, ControllerTaskNode
from apps.node_mgmt.tasks import installer as installer_tasks

pytestmark = pytest.mark.django_db


def test_timeout_controller_skips_missing_non_install_and_finished():
    assert installer_tasks.timeout_controller_install_task(999999) is None
    region = CloudRegion.objects.create(name="timeout-region")
    other = ControllerTask.objects.create(
        cloud_region=region, type="uninstall", status="running", package_version_id=1
    )
    assert installer_tasks.timeout_controller_install_task(other.id) is None
    finished = ControllerTask.objects.create(
        cloud_region=region, type="install", status="success", package_version_id=1
    )
    assert installer_tasks.timeout_controller_install_task(finished.id) is None


def test_timeout_controller_marks_connectivity_waiting_as_error(monkeypatch):
    region = CloudRegion.objects.create(name="timeout-ok")
    task = ControllerTask.objects.create(
        cloud_region=region, type="install", status="running", package_version_id=1
    )
    node = ControllerTaskNode.objects.create(
        task=task,
        ip="10.0.0.9",
        os="linux",
        port=22,
        username="root",
        password="p",
        status="running",
        result={
            InstallerConstants.EXECUTION_PHASE_KEY: InstallerConstants.EXECUTION_PHASE_CONNECTIVITY_WAITING,
            "steps": [{"action": "connectivity_check", "status": "running"}],
        },
    )
    monkeypatch.setattr(installer_tasks, "_collect_failure_context_from_node", lambda n: {"ip": n.ip})
    monkeypatch.setattr(installer_tasks, "_dispatch_or_finalize_controller_task", lambda task_id: None)
    installer_tasks.timeout_controller_install_task(task.id)
    node.refresh_from_db()
    last = (node.result or {}).get("steps", [])[-1]
    assert last["action"] == "connectivity_check"
    assert last["status"] in (InstallerConstants.STEP_STATUS_ERROR, "error") or node.status == "error"
