"""SSH 脚本执行、仅 stdout 输出，以及路径/URI 辅助函数。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.metis.llm.tools.ssh import execute as exe
from apps.opspilot.metis.llm.tools.ssh.utils import (
    format_file_size,
    parse_ssh_uri,
    prepare_ssh_config,
    resolve_key_path,
    validate_host_params,
)

pytestmark = pytest.mark.unit


def _ssh_streams(stdout="ok\n", stderr="", exit_code=0):
    stdout_obj = MagicMock()
    stdout_obj.read.return_value = stdout.encode()
    stdout_obj.channel.recv_exit_status.return_value = exit_code
    stderr_obj = MagicMock()
    stderr_obj.read.return_value = stderr.encode()
    return MagicMock(), stdout_obj, stderr_obj


def test_ssh_execute_script_writes_stdin_and_error_path():
    client = MagicMock()
    stdin, stdout, stderr = _ssh_streams("script-ok", "", 0)
    client.exec_command.return_value = (stdin, stdout, stderr)
    with patch.object(exe, "create_ssh_client", return_value=client), patch.object(
        exe, "prepare_ssh_config", return_value={"timeout": 15}
    ):
        out = exe.ssh_execute_script.invoke(
            {
                "host": "10.0.0.1",
                "username": "root",
                "password": "p",
                "script_content": "echo hi",
                "interpreter": "/bin/bash",
            }
        )
    assert out["success"] is True
    assert out["command"] == "<script via /bin/bash>"
    stdin.write.assert_called_once_with("echo hi")
    stdin.close.assert_called_once()
    client.close.assert_called_once()

    with patch.object(exe, "create_ssh_client", side_effect=RuntimeError("refused")):
        failed = exe.ssh_execute_script.invoke(
            {"host": "10.0.0.1", "username": "root", "password": "p", "script_content": "echo hi"}
        )
    duration = failed.pop("duration")
    assert isinstance(duration, float)
    assert duration >= 0
    assert failed == {
        "stdout": "",
        "stderr": "refused",
        "exit_code": -1,
        "success": False,
        "command": "<script>",
        "error": "脚本执行失败: refused",
    }


def test_ssh_get_command_output_returns_stdout_or_raises():
    with patch.object(exe, "ssh_execute_command", return_value={"success": True, "stdout": "uptime"}):
        assert exe.ssh_get_command_output.invoke(
            {"host": "10.0.0.1", "username": "root", "password": "p", "command": "uptime"}
        ) == "uptime"
    with patch.object(
        exe,
        "ssh_execute_command",
        return_value={"success": False, "stderr": "denied", "error": "命令执行失败: denied"},
    ):
        with pytest.raises(Exception, match="命令执行失败: denied"):
            exe.ssh_get_command_output.invoke(
                {"host": "10.0.0.1", "username": "root", "password": "p", "command": "uptime"}
            )


def test_resolve_key_path_default_and_missing(tmp_path, monkeypatch):
    import os

    from apps.opspilot.metis.llm.tools.ssh import utils as ssh_utils

    real_exists = ssh_utils.os.path.exists

    def _exists(path):
        return str(path).startswith(str(tmp_path)) and real_exists(path)

    monkeypatch.setattr(ssh_utils.os.path, "exists", _exists)
    assert resolve_key_path(None) is None
    assert resolve_key_path(str(tmp_path / "no-such-key")) is None
    key = tmp_path / "id_rsa"
    key.write_text("k", encoding="utf-8")
    assert resolve_key_path(str(key)) == os.path.abspath(str(key))


def test_format_file_size_and_parse_ssh_uri():
    assert format_file_size(512) == "512.00 B"
    assert format_file_size(2048) == "2.00 KB"
    assert format_file_size(1024 ** 5) == "1.00 PB"
    parsed = parse_ssh_uri("ssh://root@10.0.0.1:2222/var/log")
    assert parsed == {"host": "10.0.0.1", "username": "root", "port": 2222, "path": "/var/log"}
    simple = parse_ssh_uri("ubuntu@host.local:22")
    assert simple["username"] == "ubuntu"
    assert simple["host"] == "host.local"
    assert simple["port"] == 22
    with pytest.raises(ValueError, match="主机地址格式无效"):
        validate_host_params("-bad", "root")
    assert parse_ssh_uri("10.0.0.8") == {"host": "10.0.0.8", "username": None, "port": 22, "path": None}
    cfg = prepare_ssh_config(
        {"configurable": {"ssh_timeout": 7, "ssh_port": 2222, "ssh_key_path": "/tmp/k"}}
    )
    assert cfg == {"timeout": 7, "port": 2222, "key_path": "/tmp/k", "look_for_keys": True}


def test_ssh_execute_command_cwd_env_and_error():
    client = MagicMock()
    stdin, stdout, stderr = _ssh_streams("out", "", 0)
    client.exec_command.return_value = (stdin, stdout, stderr)
    with patch.object(exe, "create_ssh_client", return_value=client), patch.object(
        exe, "prepare_ssh_config", return_value={"timeout": 15}
    ):
        out = exe.ssh_execute_command.invoke(
            {
                "host": "10.0.0.1",
                "username": "root",
                "password": "p",
                "command": "ls",
                "working_directory": "/tmp",
                "environment": {"A": "1"},
            }
        )
    assert out["success"] is True
    assert out["stdout"] == "out"
    client.exec_command.assert_called_once()
    full_cmd = client.exec_command.call_args.args[0]
    assert full_cmd == "export A=1; cd /tmp && ls"

    with patch.object(exe, "create_ssh_client", side_effect=RuntimeError("down")):
        failed = exe.ssh_execute_command.invoke(
            {"host": "10.0.0.1", "username": "root", "password": "p", "command": "uptime"}
        )
    assert failed["success"] is False
    assert failed["exit_code"] == -1
    assert failed["error"] == "命令执行失败: down"
    assert failed["command"] == "uptime"
