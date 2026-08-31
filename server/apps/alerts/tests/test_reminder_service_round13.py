"""提醒服务剩余分支契约：异常兜底、停用、入队推进与到期处理。

对照 spec/prd/告警中心·告警：提醒任务必须按状态/次数停用，异常不得抛出到调用方。
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.alerts.constants.constants import AlertStatus
from apps.alerts.models.alert_operator import AlertAssignment, AlertReminderTask
from apps.alerts.models.models import Alert
from apps.alerts.service.reminder_service import ReminderService as RS

pytestmark = pytest.mark.django_db


def _make_alert(alert_id="R13-A1", level="0", status=AlertStatus.PENDING):
    return Alert.objects.create(
        alert_id=alert_id, level=level, title="t", content="c",
        fingerprint="fp-" + alert_id, status=status,
    )


def _make_assignment(name="分派-r13", frequency=None, is_active=True):
    return AlertAssignment.objects.create(
        name=name, match_type="all",
        notification_frequency=frequency or {"0": {"interval_minutes": 30, "max_count": 5}},
        is_active=is_active,
    )


def _make_reminder(alert, assignment, **kwargs):
    defaults = dict(
        is_active=True,
        current_frequency_minutes=30,
        current_max_reminders=5,
        reminder_count=0,
        next_reminder_time=timezone.now() - timedelta(minutes=1),
    )
    defaults.update(kwargs)
    return AlertReminderTask.objects.create(alert=alert, assignment=assignment, **defaults)


# --------------------------------------------------------------------------
# create_reminder_task / ensure_reminder_task / stop_reminder_task 异常与守卫
# --------------------------------------------------------------------------


def test_create_reminder_task_exception_returns_none():
    """创建路径抛错必须吞掉并返回 None，不得向外抛。"""
    alert = _make_alert()
    assignment = _make_assignment()
    with patch.object(AlertReminderTask.objects, "filter", side_effect=RuntimeError("db down")):
        assert RS.create_reminder_task(alert, assignment) is None


def test_ensure_reminder_task_reuses_existing_assignment():
    """未传入 assignment 时，从已有提醒任务回填分派策略并重建。"""
    alert = _make_alert()
    assignment = _make_assignment()
    _make_reminder(alert, assignment, is_active=False)
    task = RS.ensure_reminder_task(alert)
    assert task is not None
    assert task.is_active is True
    assert task.assignment_id == assignment.id


def test_ensure_reminder_task_inactive_assignment_returns_none():
    """分派策略未启用时不得恢复提醒。"""
    alert = _make_alert()
    assignment = _make_assignment(is_active=False)
    assert RS.ensure_reminder_task(alert, assignment=assignment) is None


def test_ensure_reminder_task_exception_returns_none():
    alert = _make_alert()
    with patch.object(AlertReminderTask.objects, "filter", side_effect=RuntimeError("boom")):
        assert RS.ensure_reminder_task(alert) is None


def test_stop_reminder_task_exception_returns_false():
    alert = _make_alert()
    with patch(
        "apps.alerts.service.reminder_service.transaction.atomic",
        side_effect=RuntimeError("tx fail"),
    ):
        assert RS.stop_reminder_task(alert) is False


# --------------------------------------------------------------------------
# _update_reminder_task：剩余时间为负立即到期；异常返回 False
# --------------------------------------------------------------------------


def test_update_reminder_task_remaining_elapsed_sets_next_to_now():
    """频率缩短且距上次已超过新间隔时，下次提醒应立即到期。"""
    alert = _make_alert()
    assignment = _make_assignment()
    now = timezone.now()
    reminder = _make_reminder(
        alert, assignment,
        current_frequency_minutes=60,
        last_reminder_time=now - timedelta(minutes=50),
        next_reminder_time=now + timedelta(minutes=10),
    )
    before = timezone.now()
    assert RS._update_reminder_task(reminder, 5, 8) is True
    reminder.refresh_from_db()
    assert reminder.current_frequency_minutes == 5
    assert reminder.next_reminder_time <= timezone.now()
    assert reminder.next_reminder_time >= before


def test_update_reminder_task_exception_returns_false():
    alert = _make_alert()
    assignment = _make_assignment()
    reminder = _make_reminder(alert, assignment)
    with patch.object(reminder, "save", side_effect=RuntimeError("save fail")):
        assert RS._update_reminder_task(reminder, 15, 3) is False


# --------------------------------------------------------------------------
# check_and_process_reminders 各守卫
# --------------------------------------------------------------------------


def test_check_and_process_skips_missing_or_future_reminder():
    """查询到的 id 已不存在，或锁内发现下次提醒尚未到期，均不计 processed。"""
    alert = _make_alert(alert_id="R13-SKIP")
    assignment = _make_assignment()
    reminder = _make_reminder(
        alert, assignment,
        next_reminder_time=timezone.now() - timedelta(minutes=1),
    )
    # 先把 next 推到未来，再让 values_list 仍返回该 pk，锁内比较会 continue
    AlertReminderTask.objects.filter(pk=reminder.pk).update(
        next_reminder_time=timezone.now() + timedelta(hours=1),
    )
    result = RS.check_and_process_reminders()
    assert result == {"processed": 0, "success": 0}

    AlertReminderTask.objects.filter(pk=reminder.pk).delete()
    # 查询窗口仍可能扫到别的任务；用 mock 注入已删除 pk
    with patch.object(
        AlertReminderTask.objects, "filter",
        wraps=AlertReminderTask.objects.filter,
    ) as mocked:
        # 只替换第一段 pending 查询的 values_list
        original_filter = AlertReminderTask.objects.filter

        def _filter(*args, **kwargs):
            qs = original_filter(*args, **kwargs)
            if "next_reminder_time__lte" in kwargs:
                class _Pending:
                    def values_list(self, *a, **k):
                        return [reminder.pk]

                return _Pending()
            return qs

        mocked.side_effect = _filter
        result = RS.check_and_process_reminders()
    assert result["processed"] == 0


def test_check_and_process_deactivates_when_max_reached():
    """待响应告警已达最大提醒次数时必须停用，且不发送。"""
    alert = _make_alert(alert_id="R13-MAX")
    assignment = _make_assignment(frequency={"0": {"interval_minutes": 30, "max_count": 2}})
    reminder = _make_reminder(alert, assignment, reminder_count=2, current_max_reminders=2)
    with patch.object(RS, "_send_reminder_notification") as send:
        result = RS.check_and_process_reminders()
    send.assert_not_called()
    assert result["processed"] == 1
    assert result["success"] == 0
    reminder.refresh_from_db()
    assert reminder.is_active is False


def test_check_and_process_counts_success_when_send_ok():
    alert = _make_alert(alert_id="R13-OK")
    assignment = _make_assignment()
    _make_reminder(alert, assignment)
    with patch.object(RS, "_send_reminder_notification", return_value=True):
        result = RS.check_and_process_reminders()
    assert result == {"processed": 1, "success": 1}


def test_check_and_process_item_exception_does_not_abort():
    """单条处理失败只记日志，其他任务继续，外层返回计数。"""
    alert = _make_alert(alert_id="R13-EX")
    assignment = _make_assignment()
    _make_reminder(alert, assignment)
    with patch.object(
        AlertReminderTask.objects, "select_for_update",
        side_effect=RuntimeError("lock fail"),
    ):
        result = RS.check_and_process_reminders()
    assert result == {"processed": 0, "success": 0}


def test_check_and_process_outer_exception_returns_zero():
    with patch.object(
        AlertReminderTask.objects, "filter",
        side_effect=RuntimeError("query fail"),
    ):
        assert RS.check_and_process_reminders() == {"processed": 0, "success": 0}


# --------------------------------------------------------------------------
# _send_reminder_notification 入队失败 / 无事务直接入队
# --------------------------------------------------------------------------


def test_send_reminder_enqueue_failure_returns_false(monkeypatch):
    alert = _make_alert(alert_id="R13-ENQ")
    assignment = _make_assignment()
    assignment.personnel = ["op1"]
    assignment.notify_channels = [{"id": 1, "channel_type": "email"}]
    assignment.save()
    reminder = _make_reminder(alert, assignment)

    monkeypatch.setattr(
        "apps.alerts.service.escalation_service.EscalationService.active_roster_for_reminder",
        staticmethod(lambda a: (None, None)),
    )
    monkeypatch.setattr(
        "apps.alerts.common.notify.dispatcher.build_channel_params",
        lambda *a, **k: [{"channel_type": "email"}],
    )

    class BoomNotify:
        @staticmethod
        def delay(params):
            raise RuntimeError("broker down")

    import apps.alerts.tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "sync_notify", BoomNotify, raising=False)
    monkeypatch.setattr(
        "apps.alerts.service.reminder_service.transaction.get_connection",
        lambda: type("C", (), {"in_atomic_block": False})(),
    )
    assert RS._send_reminder_notification(
        assignment=assignment, alert=alert, reminder_id=reminder.pk,
    ) is False


def test_send_reminder_outer_exception_returns_false(monkeypatch):
    alert = _make_alert(alert_id="R13-OUT")
    assignment = _make_assignment()
    assignment.personnel = ["op1"]
    assignment.notify_channels = [{"id": 1, "channel_type": "email"}]
    assignment.save()
    monkeypatch.setattr(
        "apps.alerts.service.escalation_service.EscalationService.active_roster_for_reminder",
        side_effect=RuntimeError("escalation down"),
    )
    assert RS._send_reminder_notification(assignment=assignment, alert=alert) is False


# --------------------------------------------------------------------------
# _advance_reminder_after_enqueue 停用 / 达上限 / 异常
# --------------------------------------------------------------------------


def test_advance_inactive_reminder_returns_true_without_increment():
    alert = _make_alert(alert_id="R13-INACT")
    assignment = _make_assignment()
    reminder = _make_reminder(alert, assignment, is_active=False, reminder_count=3)
    assert RS._advance_reminder_after_enqueue(reminder.pk) is True
    reminder.refresh_from_db()
    assert reminder.reminder_count == 3
    assert reminder.is_active is False


def test_advance_non_pending_deactivates():
    alert = _make_alert(alert_id="R13-CLOSED", status=AlertStatus.CLOSED)
    assignment = _make_assignment()
    reminder = _make_reminder(alert, assignment)
    assert RS._advance_reminder_after_enqueue(reminder.pk) is True
    reminder.refresh_from_db()
    assert reminder.is_active is False


def test_advance_already_at_max_deactivates():
    alert = _make_alert(alert_id="R13-ATMAX")
    assignment = _make_assignment(frequency={"0": {"interval_minutes": 30, "max_count": 1}})
    reminder = _make_reminder(alert, assignment, reminder_count=1, current_max_reminders=1)
    assert RS._advance_reminder_after_enqueue(reminder.pk) is True
    reminder.refresh_from_db()
    assert reminder.is_active is False
    assert reminder.reminder_count == 1


def test_advance_last_allowed_count_deactivates():
    """本次推进后达到上限，必须停用且不再写 next_reminder_time。"""
    alert = _make_alert(alert_id="R13-LAST")
    assignment = _make_assignment(frequency={"0": {"interval_minutes": 30, "max_count": 1}})
    reminder = _make_reminder(alert, assignment, reminder_count=0, current_max_reminders=1)
    old_next = reminder.next_reminder_time
    assert RS._advance_reminder_after_enqueue(reminder.pk) is True
    reminder.refresh_from_db()
    assert reminder.reminder_count == 1
    assert reminder.is_active is False
    assert reminder.next_reminder_time == old_next


def test_advance_exception_returns_false():
    with patch(
        "apps.alerts.service.reminder_service.transaction.atomic",
        side_effect=RuntimeError("tx"),
    ):
        assert RS._advance_reminder_after_enqueue(1) is False


# --------------------------------------------------------------------------
# cleanup_expired_reminders 异常
# --------------------------------------------------------------------------


def test_cleanup_expired_reminders_exception_returns_zero():
    with patch.object(AlertReminderTask.objects, "filter", side_effect=RuntimeError("db")):
        assert RS.cleanup_expired_reminders() == 0
