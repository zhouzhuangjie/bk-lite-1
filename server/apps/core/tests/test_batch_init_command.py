import pydantic.root_model  # noqa
"""apps/core/management/commands/batch_init.py 的真实行为测试。

被测对象是初始化编排命令 Command。它的核心逻辑是“按 app 分发到对应的
call_command 序列 + 错误处理策略（system_mgmt 失败则中断，其它继续）”。

策略：
- call_command 是 Django 命令调度边界，按契约打桩并记录每次调用的命令名/参数；
- preload_language_cache 是外部预热边界，打桩；
- 直接构造 Command 实例（替换 stdout/style 为可断言的轻量替身），
  调用真实 handle(...)，断言真实的分发顺序、未知模块告警、错误处理控制流、
  以及 _get_admin_password 的环境变量逻辑。
"""
from types import SimpleNamespace

import pytest

import apps.core.management.commands.batch_init as bi

pytestmark = pytest.mark.unit


class _Style:
    SUCCESS = staticmethod(lambda m: m)
    WARNING = staticmethod(lambda m: f"WARN:{m}")
    ERROR = staticmethod(lambda m: f"ERR:{m}")


def _make_command():
    cmd = bi.Command()
    cmd.stdout = SimpleNamespace(messages=[], write=lambda m: cmd.stdout.messages.append(m))
    cmd.style = _Style()
    return cmd


@pytest.fixture
def calls(monkeypatch):
    recorded = []

    def fake_call_command(name, *args, **kwargs):
        recorded.append((name, args, kwargs))

    monkeypatch.setattr(bi, "call_command", fake_call_command)
    monkeypatch.setattr(
        bi,
        "preload_language_cache",
        lambda *a, **k: {"loaded": [1], "skipped": [], "failed": []},
    )
    return recorded


class TestHandleDispatch:
    def test_single_known_app_runs_its_command_sequence(self, calls):
        cmd = _make_command()
        cmd.handle(apps="node_mgmt")
        names = [c[0] for c in calls]
        # node_mgmt 仅触发 node_init
        assert names == ["node_init"]

    def test_monitor_app_runs_plugin_init(self, calls):
        cmd = _make_command()
        cmd.handle(apps="monitor")
        assert [c[0] for c in calls] == ["plugin_init"]

    def test_multiple_apps_dispatched_in_order(self, calls):
        cmd = _make_command()
        cmd.handle(apps="log,mlops")
        assert [c[0] for c in calls] == ["log_init", "init_algorithm_config"]

    def test_console_mgmt_dispatches_to_noop_init(self, calls):
        # console_mgmt 是已知分支，但其初始化目前为空操作，不触发任何 call_command
        cmd = _make_command()
        cmd.handle(apps="console_mgmt")
        assert calls == []
        # 输出含控制台初始化提示，说明确实进入了该分支而非走未知模块告警
        assert any("控制台管理资源初始化" in m for m in cmd.stdout.messages)
        assert not any("未知模块" in m for m in cmd.stdout.messages)

    def test_unknown_app_emits_warning_and_no_command(self, calls):
        cmd = _make_command()
        cmd.handle(apps="does_not_exist")
        # 未知模块不触发任何 call_command
        assert calls == []
        # 输出含 WARNING 包裹的“未知模块”提示
        assert any("WARN:" in m and "未知模块" in m for m in cmd.stdout.messages)

    def test_empty_apps_uses_full_default_list(self, calls):
        cmd = _make_command()
        cmd.handle(apps="")
        names = [c[0] for c in calls]
        # 默认全量初始化应至少包含各模块的代表性命令
        assert "init_realm_resource" in names  # system_mgmt
        assert "model_init" in names  # cmdb
        assert "plugin_init" in names  # monitor
        assert "node_init" in names  # node_mgmt
        assert "log_init" in names  # log

    def test_system_mgmt_creates_admin_with_resolved_password(self, calls, monkeypatch):
        monkeypatch.delenv("BK_INIT_ADMIN_PASSWORD", raising=False)
        cmd = _make_command()
        cmd.handle(apps="system_mgmt")
        create_user = [c for c in calls if c[0] == "create_user"]
        assert len(create_user) == 1
        _, args, kwargs = create_user[0]
        # 默认口令为 "password"，且 admin 为超管
        assert args == ("admin", "password")
        assert kwargs.get("is_superuser") is True


class TestErrorHandlingPolicy:
    def test_system_mgmt_failure_reraises_and_aborts(self, monkeypatch):
        calls = []

        def fake_call_command(name, *args, **kwargs):
            calls.append(name)
            if name == "init_realm_resource":
                raise RuntimeError("sysmgmt boom")

        monkeypatch.setattr(bi, "call_command", fake_call_command)
        monkeypatch.setattr(
            bi, "preload_language_cache", lambda *a, **k: {"loaded": [], "skipped": [], "failed": []}
        )
        cmd = _make_command()
        # system_mgmt 初始化失败必须向上抛、中断整个批处理
        with pytest.raises(RuntimeError, match="sysmgmt boom"):
            cmd.handle(apps="system_mgmt,cmdb")
        # cmdb 的命令不应被执行
        assert "model_init" not in calls

    def test_non_system_app_failure_is_swallowed_and_continues(self, monkeypatch):
        calls = []

        def fake_call_command(name, *args, **kwargs):
            calls.append(name)
            if name == "plugin_init":  # monitor 失败
                raise RuntimeError("monitor boom")

        monkeypatch.setattr(bi, "call_command", fake_call_command)
        monkeypatch.setattr(
            bi, "preload_language_cache", lambda *a, **k: {"loaded": [], "skipped": [], "failed": []}
        )
        cmd = _make_command()
        # monitor 失败被吞，log 仍继续执行
        cmd.handle(apps="monitor,log")
        assert "log_init" in calls
        assert any("ERR:" in m and "monitor" in m for m in cmd.stdout.messages)


class TestGetAdminPassword:
    def test_env_password_used_when_set(self, monkeypatch):
        monkeypatch.setenv("BK_INIT_ADMIN_PASSWORD", "  s3cret  ")
        assert bi.Command._get_admin_password() == "s3cret"

    def test_blank_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("BK_INIT_ADMIN_PASSWORD", "   ")
        assert bi.Command._get_admin_password() == "password"

    def test_missing_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("BK_INIT_ADMIN_PASSWORD", raising=False)
        assert bi.Command._get_admin_password() == "password"


class TestPreloadLanguageCache:
    def test_preload_failure_is_swallowed_with_warning(self, monkeypatch):
        monkeypatch.setattr(bi, "call_command", lambda *a, **k: None)

        def boom(*a, **k):
            raise RuntimeError("preload boom")

        monkeypatch.setattr(bi, "preload_language_cache", boom)
        cmd = _make_command()
        # 语言预热失败不应中断初始化
        cmd.handle(apps="node_mgmt")
        assert any("WARN:" in m and "语言缓存预热失败" in m for m in cmd.stdout.messages)

    def test_add_arguments_registers_apps_option(self):
        import argparse

        parser = argparse.ArgumentParser()
        bi.Command().add_arguments(parser)
        ns = parser.parse_args(["--apps", "cmdb,log"])
        assert ns.apps == "cmdb,log"
