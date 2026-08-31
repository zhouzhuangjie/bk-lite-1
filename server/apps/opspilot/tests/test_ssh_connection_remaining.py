"""SSH 连接工具：私钥加载失败、认证/连接异常包装、探测成功与服务器信息。"""
from unittest.mock import MagicMock, patch

import paramiko
import pytest

from apps.opspilot.metis.llm.tools.ssh import connection as ssh

pytestmark = pytest.mark.unit


def test_create_ssh_client_missing_key_file():
    with patch.object(ssh, "validate_host_params"), patch.object(ssh, "resolve_key_path", return_value=None):
        with pytest.raises(ValueError, match="SSH私钥文件不存在: /no.key"):
            ssh.create_ssh_client("h", "root", private_key_path="/no.key")


def test_create_ssh_client_key_password_required_and_load_error():
    with patch.object(ssh, "validate_host_params"), patch.object(ssh, "resolve_key_path", return_value="/k"):
        with patch.object(ssh.paramiko.RSAKey, "from_private_key_file", side_effect=paramiko.PasswordRequiredException("need pass")):
            with pytest.raises(ValueError, match="私钥文件需要密码: /k"):
                ssh.create_ssh_client("h", "root", private_key_path="/k")
        with patch.object(ssh.paramiko.RSAKey, "from_private_key_file", side_effect=OSError("bad pem")):
            with pytest.raises(ValueError, match="加载私钥失败: bad pem"):
                ssh.create_ssh_client("h", "root", private_key_path="/k")


def test_create_ssh_client_wraps_connect_errors():
    client = MagicMock()
    with (
        patch.object(ssh, "validate_host_params"),
        patch.object(ssh.paramiko, "SSHClient", return_value=client),
        patch.object(ssh.paramiko, "AutoAddPolicy", return_value="policy"),
    ):
        client.connect.side_effect = paramiko.AuthenticationException("bad auth")
        with pytest.raises(paramiko.AuthenticationException, match="SSH认证失败"):
            ssh.create_ssh_client("10.0.0.1", "root", password="p")
        client.connect.side_effect = paramiko.SSHException("reset")
        with pytest.raises(paramiko.SSHException, match="SSH连接失败"):
            ssh.create_ssh_client("10.0.0.1", "root", password="p")
        client.connect.side_effect = OSError("timeout")
        with pytest.raises(Exception, match="建立SSH连接时发生未知错误"):
            ssh.create_ssh_client("10.0.0.1", "root", password="p")


def test_create_ssh_client_success_with_password():
    client = MagicMock()
    with (
        patch.object(ssh, "validate_host_params"),
        patch.object(ssh.paramiko, "SSHClient", return_value=client),
        patch.object(ssh.paramiko, "AutoAddPolicy", return_value="policy"),
    ):
        out = ssh.create_ssh_client("10.0.0.1", "root", password="p", port=2222)
    assert out is client
    kwargs = client.connect.call_args.kwargs
    assert kwargs["hostname"] == "10.0.0.1"
    assert kwargs["password"] == "p"
    assert kwargs["look_for_keys"] is False
    assert kwargs["port"] == 2222


def test_test_ssh_connection_success_and_failure():
    client = MagicMock()
    client.get_transport.return_value = SimpleTransport("SSH-2.0-OpenSSH")
    with (
        patch.object(ssh, "prepare_ssh_config", return_value={"port": 2222, "timeout": 5}),
        patch.object(ssh, "create_ssh_client", return_value=client) as ctor,
    ):
        ok = ssh.test_ssh_connection.func(host="h", username="root", password="p", config={})
    assert ok == {
        "success": True,
        "message": "成功连接到 root@h:2222",
        "server_info": {"hostname": "h", "banner": "SSH-2.0-OpenSSH"},
    }
    ctor.assert_called_once()
    client.close.assert_called_once()

    with (
        patch.object(ssh, "prepare_ssh_config", return_value={}),
        patch.object(ssh, "create_ssh_client", side_effect=RuntimeError("refused")),
    ):
        err = ssh.test_ssh_connection.func(host="h", username="root", password="p", port=22, timeout=10, config={})
    assert err == {"success": False, "message": "连接失败: root@h:22", "error": "refused"}


class SimpleTransport:
    def __init__(self, version):
        self.remote_version = version


def test_get_ssh_server_info_collects_command_output_and_closes():
    stdout = MagicMock()
    stdout.read.side_effect = [b"host1\n", b"Ubuntu\n", b"6.1\n", b"x86_64\n"]
    client = MagicMock()
    client.exec_command.return_value = (None, stdout, None)
    client.get_transport.return_value = SimpleTransport("SSH-2.0-OpenSSH")
    with (
        patch.object(ssh, "prepare_ssh_config", return_value={"timeout": 9}),
        patch.object(ssh, "create_ssh_client", return_value=client) as ctor,
    ):
        info = ssh.get_ssh_server_info.func(host="h", username="root", password="p", config={})
    assert info == {
        "hostname": "host1",
        "os_info": "Ubuntu",
        "kernel": "6.1",
        "architecture": "x86_64",
        "ssh_banner": "SSH-2.0-OpenSSH",
    }
    assert ctor.call_args.kwargs["timeout"] == 9
    client.close.assert_called_once()


def test_get_ssh_server_info_wraps_failure():
    with (
        patch.object(ssh, "prepare_ssh_config", return_value={}),
        patch.object(ssh, "create_ssh_client", side_effect=RuntimeError("down")),
    ):
        with pytest.raises(Exception, match="获取服务器信息失败: down"):
            ssh.get_ssh_server_info.func(host="h", username="root", password="p", config={})
