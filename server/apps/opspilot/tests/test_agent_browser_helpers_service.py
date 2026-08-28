"""agent_browser 工具：URL 抽取、导航 SSRF、安全提示页 ref、CLI 缺失时失败。"""
import json
from types import SimpleNamespace

import pytest

from apps.opspilot.metis.llm.tools.agent_browser import browser_tool as ab

pytestmark = pytest.mark.unit


def test_extract_url_candidates_dedupes_http_urls():
    urls = ab._extract_url_candidates(
        "see https://a.example/path and https://a.example/path",
        "also http://b.example/x",
        "",
    )
    assert urls == ["https://a.example/path", "http://b.example/x"]


def test_check_command_args_ssrf_blocks_metadata_and_skips_flags(mocker):
    mocker.patch.object(ab, "_check_url_ssrf", side_effect=lambda url: f"blocked:{url}" if "169.254" in url else None)
    assert ab._check_command_args_ssrf(["snapshot"]) is None
    assert ab._check_command_args_ssrf(["open", "--wait"]) is None
    error = ab._check_command_args_ssrf(["open", "http://169.254.169.254/latest/meta-data/"])
    assert error == "blocked:http://169.254.169.254/latest/meta-data/"


def test_check_url_ssrf_returns_none_when_validator_accepts(mocker):
    mocker.patch.object(ab, "validate_browser_url", return_value="https://ok.example/")
    assert ab._check_url_ssrf("https://ok.example/") is None
    mocker.patch.object(ab, "validate_browser_url", side_effect=ValueError("私网"))
    assert "私网" in ab._check_url_ssrf("http://10.0.0.1/")


def test_extract_security_interstitial_continue_ref_from_refs_and_snapshot_text():
    assert ab._extract_security_interstitial_continue_ref({"success": False}) == ""
    payload = {
        "data": {
            "snapshot": "此网站不支持安全连接",
            "refs": {"e12": {"name": "继续访问网站", "role": "button"}},
        }
    }
    result = {"success": True, "stdout": json.dumps(payload)}
    assert ab._extract_security_interstitial_continue_ref(result) == "@e12"

    line_payload = {
        "data": {
            "snapshot": "Continue to site ref=btn9",
            "refs": {},
        }
    }
    assert ab._extract_security_interstitial_continue_ref({"success": True, "stdout": json.dumps(line_payload)}) == "@btn9"


def test_build_session_flags_and_screenshot_path_normalization(tmp_path, monkeypatch):
    assert ab._build_session_flags("") == []
    assert ab._build_session_flags(" s1 ") == ["--session", "s1"]
    monkeypatch.setattr(ab, "_DEFAULT_SCREENSHOT_DIR", tmp_path)
    path = ab._build_default_screenshot_path(filename="shot", image_format="webp")
    assert path.endswith(".png")
    jpeg_path = ab._build_default_screenshot_path(filename="out.jpeg", image_format="jpeg")
    assert jpeg_path.endswith(".jpeg")


def test_headed_mode_reads_env_then_debug(monkeypatch):
    monkeypatch.setenv("AGENT_BROWSER_HEADED", "yes")
    assert ab._should_enable_headed_mode() is True
    monkeypatch.delenv("AGENT_BROWSER_HEADED")
    monkeypatch.setenv("AGENT_BROWSER_HEADLESS", "false")
    assert ab._should_enable_headed_mode() is True
    monkeypatch.delenv("AGENT_BROWSER_HEADLESS")
    monkeypatch.setattr(ab.settings, "DEBUG", False, raising=False)
    assert ab._should_enable_headed_mode() is False


def test_run_agent_browser_command_fails_when_binary_missing(monkeypatch):
    monkeypatch.setattr(ab, "_find_agent_browser_binary", lambda: None)
    result = ab._run_agent_browser_command(["open", "https://example.com"], timeout=1)
    assert result["success"] is False
    assert "未找到 agent-browser CLI" in result["error"]


def test_run_agent_browser_command_success_and_interrupt(monkeypatch):
    monkeypatch.setattr(ab, "_find_agent_browser_binary", lambda: "/usr/bin/agent-browser")
    monkeypatch.setattr(ab, "_should_enable_headed_mode", lambda: False)

    class _Proc:
        def __init__(self, returncode=0):
            self.returncode = returncode

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            return ("ok-stdout https://done.example", "")

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(ab.subprocess, "Popen", lambda *args, **kwargs: _Proc(0))
    result = ab._run_agent_browser_command(["snapshot"], timeout=5)
    assert result["success"] is True
    assert result["exit_code"] == 0
    assert "https://done.example" in result["url_candidates"]

    monkeypatch.setattr(ab, "is_interrupt_requested", lambda execution_id: True)
    interrupted = ab._run_agent_browser_command(["snapshot"], timeout=5, execution_id="run-1")
    assert interrupted["interrupted"] is True
    assert interrupted["success"] is False


def test_agent_browser_run_rejects_empty_timeout_and_ssrf(monkeypatch):
    empty = ab.agent_browser_run.func([])
    assert empty["success"] is False
    assert "不能为空" in empty["error"]

    timeout = ab.agent_browser_run.func(["snapshot"], timeout=0)
    assert timeout["success"] is False
    assert "timeout" in timeout["error"]

    monkeypatch.setattr(ab, "_check_command_args_ssrf", lambda args: "blocked")
    blocked = ab.agent_browser_run.func(["open", "http://169.254.169.254/"])
    assert blocked["success"] is False
    assert blocked["error"] == "blocked"

    monkeypatch.setattr(ab, "_check_command_args_ssrf", lambda args: None)
    monkeypatch.setattr(ab, "_run_agent_browser_command", lambda **kwargs: {"success": True, "command": kwargs["command"]})
    ok = ab.agent_browser_run.func(["snapshot"], timeout=3, config={"configurable": {"execution_id": "e1"}})
    assert ok["success"] is True
