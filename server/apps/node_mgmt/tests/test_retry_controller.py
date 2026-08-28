"""retry_controller：缺任务/包/节点报错；成功时加密凭据并重置为 waiting。"""
import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.node_mgmt.constants.installer import InstallerConstants
from apps.node_mgmt.models import PackageVersion
from apps.node_mgmt.models.cloud_region import CloudRegion
from apps.node_mgmt.models.installer import ControllerTask, ControllerTaskNode
from apps.node_mgmt.tasks import installer as installer_tasks
from apps.core.utils.crypto.aes_crypto import AESCryptor

pytestmark = pytest.mark.django_db


def _region():
    return CloudRegion.objects.create(name="retry-region")


def test_retry_controller_missing_task_package_and_nodes():
    with pytest.raises(BaseAppException, match="Task not found"):
        installer_tasks.retry_controller(999999, [1])

    region = _region()
    task = ControllerTask.objects.create(
        cloud_region=region, type="install", status="error", package_version_id=999999
    )
    with pytest.raises(BaseAppException, match="Package version not found"):
        installer_tasks.retry_controller(task.id, [1])

    pkg = PackageVersion.objects.create(
        type="controller", os="linux", cpu_architecture="x86_64", object="Controller", version="1.0.0", name="ctl.tar.gz"
    )
    task.package_version_id = pkg.id
    task.save(update_fields=["package_version_id"])
    with pytest.raises(BaseAppException, match="No valid nodes found"):
        installer_tasks.retry_controller(task.id, [888888])


def test_retry_controller_encrypts_password_and_resets_status(monkeypatch):
    region = _region()
    pkg = PackageVersion.objects.create(
        type="controller", os="linux", cpu_architecture="x86_64", object="Controller", version="1.0.1", name="ctl2.tar.gz"
    )
    task = ControllerTask.objects.create(
        cloud_region=region, type="install", status="error", package_version_id=pkg.id
    )
    node = ControllerTaskNode.objects.create(
        task=task,
        ip="10.1.2.3",
        os="linux",
        port=22,
        username="root",
        password="old",
        status="error",
        result={InstallerConstants.EXECUTION_ATTEMPT_KEY: 2},
    )
    monkeypatch.setattr(installer_tasks, "_dispatch_or_finalize_controller_task", lambda task_id: None)
    monkeypatch.setattr(
        installer_tasks.timeout_controller_install_task,
        "apply_async",
        lambda *a, **k: None,
    )
    installer_tasks.retry_controller(task.id, node.id, password="plain-secret")
    node.refresh_from_db()
    assert node.status == InstallerConstants.STEP_STATUS_WAITING
    assert node.result[InstallerConstants.EXECUTION_ATTEMPT_KEY] == 3
    decrypted = AESCryptor().decode(node.password)
    assert decrypted == "plain-secret"
