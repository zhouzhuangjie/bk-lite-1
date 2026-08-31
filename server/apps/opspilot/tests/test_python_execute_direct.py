"""Python 沙箱执行工具：空代码、表达式打印、语法错误与工具包装。"""
import pytest

from apps.opspilot.metis.llm.tools.python.executor import _execute_python_code, python_execute_direct

pytestmark = pytest.mark.unit


def test_execute_python_empty_and_runtime_error():
    assert _execute_python_code("") == "代码执行完成，但没有输出"
    assert _execute_python_code("   ") == "代码执行完成，但没有输出"
    out = _execute_python_code("1/0")
    assert "执行错误: division by zero" in out


def test_execute_python_wraps_last_expr_unless_print():
    assert _execute_python_code("1 + 2") == "3"
    assert _execute_python_code("print('keep')") == "keep"


def test_python_execute_direct_tool_success_and_forbidden():
    assert python_execute_direct.func(code="sum([1, 2, 3])", config={}) == "6"
    failed = python_execute_direct.func(code="import os", config={})
    assert failed == "Python直接执行工具执行失败:检测到禁止执行的语句: import"
    syntax = python_execute_direct.func(code="def (", config={})
    assert syntax.startswith("Python直接执行工具执行失败:Python代码语法错误:")
    dunder = python_execute_direct.func(code="().__class__", config={})
    assert dunder == "Python直接执行工具执行失败:检测到禁止访问的危险属性: __class__"
    from_import = python_execute_direct.func(code="from os import path", config={})
    assert from_import == "Python直接执行工具执行失败:检测到禁止执行的语句: import"
