"""自定义 SNMP 插件剩余：模板数量校验、渲染失败、下发回滚与片段守卫。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.core.utils.safe_template import TemplateSecurityError
from apps.monitor.services.custom_snmp_plugin import CustomSnmpPluginService as S

pytestmark = pytest.mark.unit


def test_get_child_template_requires_exactly_one():
    qs = MagicMock()
    qs.filter.return_value.order_by.return_value = []
    plugin = SimpleNamespace(id=1)
    with patch("apps.monitor.services.custom_snmp_plugin.MonitorPluginConfigTemplate.objects", qs):
        with pytest.raises(BaseAppException, match="缺少采集配置"):
            S.get_child_template(plugin)
        qs.filter.return_value.order_by.return_value = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
        with pytest.raises(BaseAppException, match="多份采集配置"):
            S.get_child_template(plugin)
        qs.filter.return_value.order_by.return_value = [SimpleNamespace(id=9, content="x", type="snmp", config_type="child", file_type="toml")]
        assert S.get_child_template(plugin).id == 9


def test_validate_child_template_wraps_toml_error():
    plugin = SimpleNamespace()
    child = SimpleNamespace(type="snmp")
    with (
        patch.object(S, "_build_validation_context", return_value={}),
        patch("apps.monitor.services.custom_snmp_plugin.Controller") as controller_cls,
        patch("apps.monitor.services.custom_snmp_plugin.ConfigFormat.toml_to_dict", side_effect=ValueError("bad toml")),
    ):
        controller_cls.return_value.render_template.return_value = "broken"
        with pytest.raises(BaseAppException, match="采集片段格式校验失败"):
            S._validate_child_template(plugin, child, "snippet")


def test_propagate_collect_template_rolls_back_partial_updates():
    plan = [
        {"id": "c1", "rendered_content": "new-1", "original_content": "old-1"},
        {"id": "c2", "rendered_content": "new-2", "original_content": "old-2"},
    ]
    node_mgmt = MagicMock()
    node_mgmt.update_child_config_content.side_effect = [None, RuntimeError("down")]
    with patch("apps.monitor.services.custom_snmp_plugin.NodeMgmt", return_value=node_mgmt):
        with pytest.raises(BaseAppException, match="采集模板同步失败: down"):
            S.propagate_collect_template(plan)
    assert node_mgmt.update_child_config_content.call_args_list[-1].args == ("c1", "old-1")

    node_mgmt.update_child_config_content.side_effect = [None, RuntimeError("down"), RuntimeError("rb")]
    with patch("apps.monitor.services.custom_snmp_plugin.NodeMgmt", return_value=node_mgmt):
        with pytest.raises(BaseAppException, match="回滚可能未完成: c1"):
            S.propagate_collect_template(plan)


def test_update_collect_template_rejects_empty_main_config_and_template_tokens():
    plugin = SimpleNamespace()
    with pytest.raises(BaseAppException, match="采集片段不能为空"):
        S.update_collect_template(plugin, "  ")
    with pytest.raises(BaseAppException, match="请勿修改 inputs.snmp 主配置"):
        S.update_collect_template(plugin, "[[inputs.snmp]]\n")
    with pytest.raises(BaseAppException, match="不允许包含模板语法: {{"):
        S.update_collect_template(plugin, "[[inputs.snmp.field]]\noid='{{ x }}'")
    with patch.object(S, "get_child_template"):
        with patch(
            "apps.monitor.services.custom_snmp_plugin.check_dangerous_patterns",
            side_effect=TemplateSecurityError("ssti"),
        ):
            with pytest.raises(BaseAppException, match="不安全的内容"):
                S.update_collect_template(plugin, "[[inputs.snmp.field]]\noid='.1'")
