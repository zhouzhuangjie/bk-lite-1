"""alerts.tasks：聚合锁串行化、分块、关闭/提醒失败路径。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.alerts.tasks import tasks as alert_tasks

pytestmark = pytest.mark.unit


def test_chunk_alert_ids_yields_fixed_size_slices():
    chunks = list(alert_tasks._chunk_alert_ids(["a", "b", "c", "d", "e"], 2))
    assert chunks == [["a", "b"], ["c", "d"], ["e"]]
    assert list(alert_tasks._chunk_alert_ids([], 10)) == []


def test_event_aggregation_alert_skips_when_lock_held():
    with patch.object(alert_tasks.cache, "add", return_value=False):
        assert alert_tasks.event_aggregation_alert() is None


def test_event_aggregation_alert_runs_processor_and_timeout_then_releases_lock():
    processor = MagicMock()
    timeout = MagicMock()
    timeout.check_session_timeouts.return_value = 3
    with (
        patch.object(alert_tasks.cache, "add", return_value=True),
        patch.object(alert_tasks.cache, "delete") as delete,
        patch("apps.alerts.aggregation.processor.aggregation_processor.AggregationProcessor", return_value=processor),
        patch("apps.alerts.aggregation.recovery.timeout_checker.TimeoutChecker", timeout),
    ):
        alert_tasks.event_aggregation_alert()
    processor.process_aggregation.assert_called_once()
    timeout.check_session_timeouts.assert_called_once()
    delete.assert_called_once_with(alert_tasks.AGGREGATION_LOCK_KEY)


def test_event_aggregation_alert_releases_lock_when_processor_fails():
    with (
        patch.object(alert_tasks.cache, "add", return_value=True),
        patch.object(alert_tasks.cache, "delete") as delete,
        patch(
            "apps.alerts.aggregation.processor.aggregation_processor.AggregationProcessor",
            side_effect=RuntimeError("agg boom"),
        ),
        patch("apps.alerts.aggregation.recovery.timeout_checker.TimeoutChecker") as timeout,
    ):
        timeout.check_session_timeouts.return_value = 0
        alert_tasks.event_aggregation_alert()
    delete.assert_called_once()


def test_beat_close_alert_reraises_inner_failure():
    with patch("apps.alerts.common.auto_close.AlertAutoClose", side_effect=RuntimeError("close fail")):
        with pytest.raises(RuntimeError, match="close fail"):
            alert_tasks.beat_close_alert()


def test_check_and_send_reminders_returns_error_dict():
    with patch("apps.alerts.service.reminder_service.ReminderService.check_and_process_reminders", side_effect=RuntimeError("x")):
        result = alert_tasks.check_and_send_reminders()
    assert result["processed"] == 0
    assert "x" in result["error"]


def test_async_auto_assignment_empty_chunks_and_failure():
    assert alert_tasks.async_auto_assignment_for_alerts([]) == {"total_alerts": 0, "assigned_alerts": 0}
    with patch.object(alert_tasks, "AUTO_ASSIGNMENT_CHUNK_SIZE", 2), patch.object(
        alert_tasks.async_auto_assignment_for_alerts, "delay"
    ) as delay:
        result = alert_tasks.async_auto_assignment_for_alerts(["a", "b", "c", "a"])
    assert result["chunked"] is True
    assert result["chunk_count"] == 2
    assert delay.call_count == 2

    with patch("apps.alerts.common.assignment.execute_auto_assignment_for_alerts", return_value={"total_alerts": 1, "assigned_alerts": 1, "failed_alerts": 0}):
        ok = alert_tasks.async_auto_assignment_for_alerts(["x"])
    assert ok["assigned_alerts"] == 1

    with patch("apps.alerts.common.assignment.execute_auto_assignment_for_alerts", side_effect=RuntimeError("assign fail")):
        failed = alert_tasks.async_auto_assignment_for_alerts(["y"])
    assert failed["assigned_alerts"] == 0
    assert "assign fail" in failed["error"]


def test_build_instant_alerts_empty_and_dispatches():
    assert alert_tasks.build_instant_alerts([]) == {"created": 0}
    with (
        patch("apps.alerts.aggregation.processor.instant_dispatcher._bulk_build_instant_alerts", return_value=["a1"]),
        patch("apps.alerts.aggregation.processor.instant_dispatcher._trigger_dispatch_async") as dispatch,
    ):
        result = alert_tasks.build_instant_alerts(
            [{"strategy_id": 1, "event_id": "e1"}, {"bad": True}]
        )
    assert result == {"created": 1}
    dispatch.assert_called_once_with(["a1"])


def test_sync_notify_saves_result_when_object_id_present():
    params = [
        {
            "username_list": ["alice"],
            "channel_id": 1,
            "channel_type": "email",
            "title": "t",
            "content": "c",
            "object_id": "alert-1",
        }
    ]
    with (
        patch("apps.alerts.tasks.tasks.Notify") as notify_cls,
        patch("apps.alerts.tasks.tasks.NotifyResultService") as result_cls,
    ):
        notify_cls.return_value.notify.return_value = {"result": True}
        out = alert_tasks.sync_notify(params)
    assert out == [{"result": True}]
    result_cls.return_value.save_notify_result.assert_called_once()


def test_sync_shield_and_escalation_error_paths():
    with patch("apps.alerts.common.shield.execute_shield_check_for_events", return_value={"ok": True}):
        assert alert_tasks.sync_shield(["e1"]) == {"ok": True}
    with patch("apps.alerts.common.shield.execute_shield_check_for_events", side_effect=RuntimeError("shield")):
        failed = alert_tasks.sync_shield(["e1"])
    assert failed["result"] is False
    with patch(
        "apps.alerts.service.escalation_service.EscalationService.check_and_process_escalations",
        side_effect=RuntimeError("esc"),
    ):
        esc = alert_tasks.check_and_send_escalations()
    assert esc["escalated"] == 0
    assert "esc" in esc["error"]
