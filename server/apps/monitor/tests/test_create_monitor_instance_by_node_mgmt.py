"""监控实例接入：空实例短路、身份识别失败、Controller 创建采集配置。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.models import MonitorObject
from apps.monitor.services.node_mgmt import InstanceConfigService as SVC

pytestmark = pytest.mark.django_db


def test_create_monitor_instance_returns_when_empty():
    assert SVC.create_monitor_instance_by_node_mgmt({"instances": [], "monitor_object_id": 1}) is None


def test_create_monitor_instance_network_identity_failure_raises():
    obj = MonitorObject.objects.create(name="Switch", display_name="交换机")
    with (
        patch.object(SVC, "_sanitize_instances_for_onboarding", side_effect=lambda instances, ctx: instances),
        patch.object(SVC, "_validate_instances_with_plugin_selector"),
        pytest.raises(BaseAppException, match="实例识别失败"),
    ):
        SVC.create_monitor_instance_by_node_mgmt(
            {
                "instances": [{"instance_id": "orphan", "instance_name": "bad"}],
                "monitor_object_id": obj.id,
                "collect_type": "snmp",
                "collector": "telegraf",
            }
        )


def test_create_monitor_instance_runs_controller_inside_transaction():
    obj = MonitorObject.objects.create(name="GenericApp", display_name="应用")
    instances = [{"instance_id": "app-1", "instance_name": "app-1", "group_ids": [1]}]
    controller = MagicMock()
    with (
        patch.object(SVC, "_sanitize_instances_for_onboarding", side_effect=lambda instances, ctx: instances),
        patch.object(SVC, "_validate_instances_with_plugin_selector"),
        patch.object(
            SVC,
            "_prepare_instances_for_creation",
            return_value=(instances, [], []),
        ) as prepare,
        patch.object(SVC, "_create_instances_in_db", return_value=(["app-1"], [11])) as create_db,
        patch("apps.monitor.services.node_mgmt.Controller", return_value=controller) as ctrl_cls,
        patch.object(SVC, "_validate_expected_collect_configs") as validate_cfg,
    ):
        SVC.create_monitor_instance_by_node_mgmt(
            {
                "instances": instances,
                "monitor_object_id": obj.id,
                "collect_type": "app",
                "collector": "telegraf",
                "monitor_plugin_id": 9,
                "configs": [{"type": "base"}],
            },
            actor_context={"username": "u", "domain": "d", "current_team": 1},
        )
    prepare.assert_called_once()
    create_db.assert_called_once()
    ctrl_cls.assert_called_once()
    controller.controller.assert_called_once()
    validate_cfg.assert_called_once()


def test_create_monitor_instance_wraps_unexpected_errors():
    obj = MonitorObject.objects.create(name="WrapErr", display_name="包装")
    with (
        patch.object(SVC, "_sanitize_instances_for_onboarding", side_effect=lambda instances, ctx: instances),
        patch.object(SVC, "_validate_instances_with_plugin_selector"),
        patch.object(SVC, "_prepare_instances_for_creation", side_effect=RuntimeError("db down")),
        pytest.raises(BaseAppException, match="实例数据准备失败"),
    ):
        SVC.create_monitor_instance_by_node_mgmt(
            {
                "instances": [{"instance_id": "x", "instance_name": "x"}],
                "monitor_object_id": obj.id,
            }
        )


def test_create_monitor_instance_skips_when_prepare_returns_nothing():
    obj = MonitorObject.objects.create(name="SkipEmpty", display_name="跳过")
    with (
        patch.object(SVC, "_sanitize_instances_for_onboarding", side_effect=lambda instances, ctx: instances),
        patch.object(SVC, "_validate_instances_with_plugin_selector"),
        patch.object(SVC, "_prepare_instances_for_creation", return_value=([], [], [])),
        patch("apps.monitor.services.node_mgmt.Controller") as ctrl_cls,
    ):
        assert (
            SVC.create_monitor_instance_by_node_mgmt(
                {
                    "instances": [{"instance_id": "x", "instance_name": "x"}],
                    "monitor_object_id": obj.id,
                }
            )
            is None
        )
    ctrl_cls.assert_not_called()
