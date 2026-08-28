"""node_mgmt.utils.step_tracker 纯函数：安装/动作步骤状态机。

断言步骤追加、按 action 更新、以及 advance 时先结束 running 再追加后续步骤。
"""
import pytest

from apps.node_mgmt.utils import step_tracker as st

pytestmark = pytest.mark.unit


def test_build_step_includes_details_only_when_provided():
    step = st.build_step("install", "running", "开始安装", timestamp="t0")
    assert step == {
        "action": "install",
        "status": "running",
        "message": "开始安装",
        "timestamp": "t0",
    }
    with_details = st.build_step("install", "ok", "完成", timestamp="t1", details={"code": 0})
    assert with_details["details"] == {"code": 0}


def test_clone_steps_copies_nested_details_and_fills_missing_timestamp():
    original = [{"action": "a", "status": "running", "message": "m", "details": {"k": 1}}]
    cloned = st.clone_steps(original, timestamp="t-fill")
    assert cloned[0]["timestamp"] == "t-fill"
    cloned[0]["details"]["k"] = 99
    assert original[0]["details"]["k"] == 1


def test_append_step_mutates_result_and_returns_the_new_step():
    result = {}
    step = st.append_step(result, "download", "running", "拉取包", timestamp="t2")
    assert result["steps"] == [step]
    assert step["action"] == "download"


def test_update_last_running_step_only_touches_trailing_running():
    result = {
        "steps": [
            {"action": "a", "status": "ok", "message": "done", "timestamp": "t0"},
            {"action": "b", "status": "running", "message": "ing", "timestamp": "t1"},
        ]
    }
    assert st.update_last_running_step(result, "ok", "完成", details={"n": 1}, timestamp="t2") is True
    assert result["steps"][-1]["status"] == "ok"
    assert result["steps"][-1]["details"] == {"n": 1}

    idle = {"steps": [{"action": "a", "status": "ok", "message": "x", "timestamp": "t0"}]}
    assert st.update_last_running_step(idle, "ok", "noop") is False


def test_update_first_running_step_skips_completed_prefix():
    result = {
        "steps": [
            {"action": "a", "status": "ok", "message": "done", "timestamp": "t0"},
            {"action": "b", "status": "running", "message": "ing", "timestamp": "t1"},
            {"action": "c", "status": "running", "message": "later", "timestamp": "t2"},
        ]
    }
    assert st.update_first_running_step(result, "failed", "超时", timestamp="t3") is True
    assert result["steps"][1]["status"] == "failed"
    assert result["steps"][2]["status"] == "running"


def test_update_step_by_action_updates_first_match_latest_updates_last():
    result = {
        "steps": [
            {"action": "push", "status": "running", "message": "1", "timestamp": "t0"},
            {"action": "push", "status": "running", "message": "2", "timestamp": "t1"},
        ]
    }
    assert st.update_step_by_action(result, "push", "ok", "first", timestamp="t2") is True
    assert result["steps"][0]["message"] == "first"
    assert result["steps"][1]["message"] == "2"

    assert st.update_latest_step_by_action(result, "push", "ok", "last", timestamp="t3") is True
    assert result["steps"][1]["message"] == "last"
    assert st.update_step_by_action(result, "missing", "ok", "x") is False


def test_advance_step_finishes_running_then_appends_cloned_next():
    result = {"steps": [{"action": "prep", "status": "running", "message": "ing", "timestamp": "t0"}]}
    steps = st.advance_step(
        result,
        "ok",
        "准备完成",
        next_steps=[{"action": "install", "status": "running", "message": "安装中"}],
        timestamp="t9",
    )
    assert steps[0]["status"] == "ok"
    assert steps[0]["message"] == "准备完成"
    assert steps[1]["action"] == "install"
    assert steps[1]["timestamp"] == "t9"
