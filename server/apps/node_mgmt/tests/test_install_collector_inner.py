"""install_collector：缺任务短路；_install_collector_inner 缺包抛错。"""
import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.node_mgmt.models.installer import CollectorTask
from apps.node_mgmt.tasks import installer as installer_tasks

pytestmark = pytest.mark.django_db


def test_install_collector_missing_task_returns():
    assert installer_tasks.install_collector(999999) is None


def test_install_collector_inner_missing_package_raises():
    task = CollectorTask.objects.create(type="install", status="pending", package_version_id=999999)
    with pytest.raises(BaseAppException, match="Package version not found"):
        installer_tasks._install_collector_inner(task)
    task.refresh_from_db()
    assert task.status == "pending"
