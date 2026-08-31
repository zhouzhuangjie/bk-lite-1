"""uninstall_controller：缺任务短路、无凭据记错、成功卸载删除节点并清空密钥。"""
from unittest.mock import patch

import pytest

from apps.core.utils.crypto.aes_crypto import AESCryptor
from apps.node_mgmt.models import Node
from apps.node_mgmt.models.cloud_region import CloudRegion
from apps.node_mgmt.models.installer import ControllerTask, ControllerTaskNode
from apps.node_mgmt.tasks import installer as installer_tasks

pytestmark = pytest.mark.django_db


def test_uninstall_controller_missing_task_returns():
    assert installer_tasks.uninstall_controller(999999) is None


def test_uninstall_controller_without_credentials_records_error():
    region = CloudRegion.objects.create(name="uninst-no-cred")
    task = ControllerTask.objects.create(cloud_region=region, type="uninstall", status="pending")
    node = ControllerTaskNode.objects.create(
        task=task,
        ip="10.1.1.1",
        os="linux",
        port=22,
        username="root",
        password="",
        private_key="",
        status="waiting",
        result={},
    )
    with patch.object(installer_tasks, "exec_command_to_remote") as remote:
        installer_tasks.uninstall_controller(task.id)
    remote.assert_not_called()
    node.refresh_from_db()
    task.refresh_from_db()
    assert task.status == "finished"
    assert node.status == "error"
    steps = node.result["steps"]
    assert steps[0]["action"] == "credential_check"
    assert steps[0]["status"] == "error"
    assert steps[0]["message"] == (
        "No authentication method provided. Password or private key is required."
    )
    assert node.result["final_message"] == "Credential validation failed"
    assert node.result["overall_status"] == "error"


def test_uninstall_controller_success_deletes_node_and_clears_secrets():
    region = CloudRegion.objects.create(name="uninst-ok")
    Node.objects.create(
        id="node-uninst-1",
        name="n1",
        ip="10.2.2.2",
        operating_system="linux",
        collector_configuration_directory="/etc/sidecar",
        cloud_region=region,
    )
    aes = AESCryptor()
    task = ControllerTask.objects.create(
        cloud_region=region, type="uninstall", status="pending", work_node="worker-1"
    )
    node = ControllerTaskNode.objects.create(
        task=task,
        ip="10.2.2.2",
        os="linux",
        port=22,
        username="root",
        password=aes.encode("plain-pass"),
        private_key="",
        status="waiting",
        result={},
    )
    with patch.object(installer_tasks, "exec_command_to_remote") as remote, patch.object(
        installer_tasks, "get_uninstall_command", return_value="stop-ctl"
    ):
        installer_tasks.uninstall_controller(task.id)
    assert remote.call_count == 2
    assert remote.call_args_list[0].args[4] == "stop-ctl"
    task.refresh_from_db()
    node.refresh_from_db()
    assert task.status == "finished"
    assert node.status == "success"
    assert node.password == ""
    assert Node.objects.filter(ip="10.2.2.2", cloud_region=region).count() == 0
