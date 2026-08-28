"""browser_use 工具纯函数：登录失败检测、会话缓存、任务拼接、日志脱敏。"""
import os
import time

import pytest

from apps.opspilot.metis.llm.tools.browser_use import browser_tool as bt

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_session_cache():
    bt._SESSION_CACHE.clear()
    yield
    for cached in list(bt._SESSION_CACHE.values()):
        path = cached.get("user_data_dir")
        if path and os.path.isdir(path):
            try:
                os.rmdir(path)
            except OSError:
                import shutil

                shutil.rmtree(path, ignore_errors=True)
    bt._SESSION_CACHE.clear()


def test_detect_login_failure_matches_page_error_and_skips_hypotheticals():
    failed, keyword = bt._detect_login_failure("登录失败：用户名或密码错误")
    assert failed is True
    assert keyword in bt.LOGIN_FAILURE_PATTERNS
    assert keyword in "登录失败：用户名或密码错误"

    skipped, skipped_keyword = bt._detect_login_failure("If login fail, retry with another account")
    assert skipped is False
    assert skipped_keyword is None

    empty, empty_keyword = bt._detect_login_failure("")
    assert empty is False
    assert empty_keyword is None


def test_get_session_key_prefers_top_level_trace_id():
    assert bt._get_session_key(None) is None
    assert bt._get_session_key({}) is None
    assert bt._get_session_key({"trace_id": "t-1"}) == "trace_t-1"
    assert bt._get_session_key({"configurable": {"trace_id": "t-2"}}) == "trace_t-2"
    assert bt._get_session_key({"configurable": {"thread_id": "th"}}) == "thread_th"
    assert bt._get_session_key({"configurable": {"run_id": "r9"}}) == "run_r9"


def test_persistent_user_data_dir_reuses_session_and_expires():
    config = {"trace_id": "same-run"}
    first = bt._get_persistent_user_data_dir(config)
    second = bt._get_persistent_user_data_dir(config)
    assert first == second
    assert os.path.isdir(first)
    assert bt._get_persistent_user_data_dir(None) is None

    bt._SESSION_CACHE["trace_same-run"]["created_at"] = time.time() - bt._SESSION_CACHE_TTL - 10
    bt._cleanup_expired_sessions()
    assert "trace_same-run" not in bt._SESSION_CACHE


def test_validate_url_delegates_to_shared_ssrf_guard(mocker):
    mocker.patch(
        "apps.opspilot.metis.llm.tools.browser_use.browser_tool.validate_browser_url",
        return_value="https://safe.example/",
    )
    assert bt._validate_url("https://safe.example/") == "https://safe.example/"


def test_forced_browser_task_ignores_low_signal_and_merges_delta():
    assert bt._is_low_signal_message("开始执行") is True
    assert bt._is_low_signal_message("打开告警详情页") is False
    assert bt._build_forced_browser_task("", "补充", "llm") == "llm"
    assert bt._build_forced_browser_task("基础任务", "开始", None) == "基础任务"
    merged = bt._build_forced_browser_task("基础任务", "只看未恢复告警", None)
    assert "基础任务" in merged
    assert "只看未恢复告警" in merged


def test_task_event_payload_truncates_and_redacts_secrets(monkeypatch):
    monkeypatch.setattr(bt, "BROWSER_TASK_EVENT_MAX_LEN", 20)
    payload = bt._build_browser_task_event_payload("browse_website", "https://a", "x" * 50)
    assert payload["truncated"] is True
    assert payload["task_final"] == "x" * 20
    redacted = bt._redact_task_for_log("login as admin01 with hunter2xx", {"x_username": "admin01", "x_password": "hunter2xx"})
    assert "admin01" not in redacted
    assert "hunter2xx" not in redacted
    assert "***" in redacted
