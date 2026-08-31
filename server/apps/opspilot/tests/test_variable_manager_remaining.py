"""VariableManager：非字符串透传、安全模板拒绝与嵌套结构解析。"""
from unittest.mock import patch

import pytest

from apps.core.utils.safe_template import TemplateSecurityError
from apps.opspilot.utils.chat_flow_utils.engine.core.variable_manager import VariableManager

pytestmark = pytest.mark.unit


def test_resolve_template_passthrough_security_error_and_fallback():
    vm = VariableManager()
    vm.set_variable("name", "alice")
    assert vm.resolve_template(12) == 12
    assert vm.resolve_template("hi {{ name }}") == "hi alice"

    with pytest.raises(TemplateSecurityError):
        vm.resolve_template("{{ ''.__class__ }}")

    with patch(
        "apps.opspilot.utils.chat_flow_utils.engine.core.variable_manager.safe_render",
        side_effect=ValueError("render boom"),
    ):
        assert vm.resolve_template("hi {{ name }}") == "hi {{ name }}"


def test_resolve_nested_dict_and_list_templates():
    vm = VariableManager()
    vm.set_variable("user", "bob")
    vm.set_variable("n", 3)
    out = vm.resolve_template_dict(
        {
            "greet": "hello {{ user }}",
            "count": 3,
            "nested": {"msg": "{{ user }}", "keep": True},
            "items": ["{{ user }}", 9],
        }
    )
    assert out == {
        "greet": "hello bob",
        "count": 3,
        "nested": {"msg": "bob", "keep": True},
        "items": ["bob", 9],
    }
    assert vm.resolve_template_list(["{{ user }}", {"x": "{{ user }}"}]) == ["bob", {"x": "bob"}]
    vm.delete_variable("user")
    assert vm.get_variable("user") is None
    assert vm.get_all_variables() == {"n": 3}
