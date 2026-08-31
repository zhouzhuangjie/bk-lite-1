"""告警生命周期通知：空列表/跳过范围/无渠道/发送成功写 notice_logs。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.monitor.models import MonitorAlert
from apps.monitor.services.alert_lifecycle_notify import (
    NOTIFY_SCOPE_ALERT_CENTER_ONLY,
    NOTIFY_SCOPE_NONE,
    AlertLifecycleNotifier,
)
from apps.system_mgmt.models import Channel

pytestmark = pytest.mark.django_db


def _alert(**kwargs):
    defaults = dict(
        content="cpu high",
        level="warning",
        status="new",
        notice_type_ids=[],
        notice_users=["alice"],
        notice_logs=[],
        alert_center_notified=False,
    )
    defaults.update(kwargs)
    return MonitorAlert.objects.create(**defaults)


def test_notify_alerts_empty_and_none_scope_reset_flags():
    notifier = AlertLifecycleNotifier()
    assert notifier.notify_alerts([], "created") is None

    alert = _alert()
    notifier.notify_alerts([alert], "created", notify_scope=NOTIFY_SCOPE_NONE)
    alert.refresh_from_db()
    assert alert.alert_center_notified is True


def test_notify_alerts_skips_without_channels_and_records_success():
    skipped = _alert(notice_type_ids=[])
    AlertLifecycleNotifier().notify_alerts([skipped], "created")
    skipped.refresh_from_db()
    assert skipped.notice_logs == []
    assert skipped.alert_center_notified is True

    channel = Channel.objects.create(
        name="im",
        channel_type="email",
        config={},
        description="",
        team=[1],
    )
    alert = _alert(notice_type_ids=[channel.id], notice_users=["bob"])
    log_entry = {
        "time": "t",
        "action": "created",
        "channel_id": channel.id,
        "success": True,
    }
    with patch.object(
        AlertLifecycleNotifier,
        "_send_to_channel",
        return_value=[(alert, log_entry)],
    ) as send:
        AlertLifecycleNotifier().notify_alerts([alert], "created")
    send.assert_called_once()
    assert send.call_args.args[0] == channel.id
    assert send.call_args.args[1] == ["bob"]
    alert.refresh_from_db()
    assert alert.notice_logs[-1]["success"] is True
    assert alert.alert_center_notified is True


def test_notify_alerts_swallows_channel_errors_into_logs():
    channel = Channel.objects.create(
        name="im-err",
        channel_type="email",
        config={},
        description="",
        team=[1],
    )
    alert = _alert(notice_type_ids=[channel.id])
    with patch.object(
        AlertLifecycleNotifier,
        "_send_to_channel",
        side_effect=RuntimeError("nats down"),
    ):
        AlertLifecycleNotifier().notify_alerts([alert], "created")
    alert.refresh_from_db()
    assert alert.notice_logs[-1]["success"] is False
    assert "nats down" in alert.notice_logs[-1]["error"]


def test_should_notify_channel_respects_policy_and_alert_center_only():
    policy = SimpleNamespace(notice=False, notice_type_ids=[1], notice_users=["u"])
    notifier = AlertLifecycleNotifier(policy=policy)
    channel = SimpleNamespace(channel_type="email", config={})
    alert = SimpleNamespace(notice_logs=[], notice_type_ids=[], notice_users=[])
    assert notifier._should_notify_channel(alert, channel, 1, "created", "all_configured") is False
    alert.notice_logs = [{"action": "created", "channel_id": 1, "success": True}]
    assert notifier._should_notify_channel(alert, channel, 1, "recovered", "all_configured") is True
    nats = SimpleNamespace(channel_type="nats", config={"method_name": "receive_alert_events"})
    assert notifier._should_notify_channel(alert, nats, 1, "upgraded", "all_configured") is True
    assert notifier._should_notify_channel(alert, channel, 1, "closed", NOTIFY_SCOPE_ALERT_CENTER_ONLY) is False
    policy_on = SimpleNamespace(notice=True, notice_type_ids=[7], notice_users=["u"])
    notifier_on = AlertLifecycleNotifier(policy_on)
    empty = SimpleNamespace(notice_logs=[], notice_type_ids=[], notice_users=[])
    assert notifier_on._resolve_notice_type_ids(empty) == [7]
    assert notifier_on._resolve_notice_users(empty) == ["u"]
    assert notifier._resolve_notice_type_ids(empty) == []
