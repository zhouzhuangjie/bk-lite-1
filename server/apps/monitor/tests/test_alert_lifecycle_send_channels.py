"""AlertLifecycleNotifier：普通通道发送、告警中心推送与补偿入口。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.monitor.models import MonitorAlert
from apps.monitor.services.alert_lifecycle_notify import AlertLifecycleNotifier
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
        monitor_instance_id="h1",
        monitor_instance_name="host-1",
        value=95.0,
    )
    defaults.update(kwargs)
    return MonitorAlert.objects.create(**defaults)


def test_send_normal_notice_success_and_exception():
    policy = SimpleNamespace(name="cpu-policy")
    notifier = AlertLifecycleNotifier(policy)
    alert = _alert()
    with patch(
        "apps.monitor.services.alert_lifecycle_notify.SystemMgmtUtils.send_msg_with_channel",
        return_value={"result": True},
    ) as send:
        results = notifier._send_normal_notice(11, "email", ["alice"], [alert], "created", "bob", "")
    send.assert_called_once()
    title, content, users = send.call_args.args[1], send.call_args.args[2], send.call_args.args[3]
    assert title == "告警产生：cpu-policy"
    assert "cpu high" in content
    assert "host-1" in content
    assert users == ["alice"]
    assert results[0][0].id == alert.id
    assert results[0][1]["success"] is True
    assert results[0][1]["channel_id"] == 11

    with patch(
        "apps.monitor.services.alert_lifecycle_notify.SystemMgmtUtils.send_msg_with_channel",
        side_effect=RuntimeError("smtp-down"),
    ):
        failed = notifier._send_normal_notice(11, "email", ["alice"], [alert], "closed", "bob", "ack")
    assert failed[0][1]["success"] is False
    assert failed[0][1]["error"] == "smtp-down"


def test_push_to_alert_center_builds_events_and_records_failure():
    policy = SimpleNamespace(name="cpu-policy", organizations=[9])
    notifier = AlertLifecycleNotifier(policy)
    alert = _alert()
    with patch(
        "apps.monitor.services.alert_lifecycle_notify.SystemMgmtUtils.send_msg_with_channel",
        return_value={"result": True},
    ) as send:
        results = notifier._push_to_alert_center(22, "alert-center", [alert], "created", "sys", "new")
    payload = send.call_args.args[2]
    assert payload["source_id"] == "nats"
    assert payload["pusher"] == "lite-monitor"
    event = payload["events"][0]
    assert event["external_id"] == str(alert.id)
    assert event["title"] == "cpu high"
    assert event["level"] == "2"
    assert event["value"] == 95.0
    assert results[0][1]["is_alert_center"] is True
    assert results[0][1]["success"] is True

    with patch(
        "apps.monitor.services.alert_lifecycle_notify.SystemMgmtUtils.send_msg_with_channel",
        return_value={"result": False, "message": "nats-down"},
    ):
        failed = notifier._push_to_alert_center(22, "alert-center", [alert], "created", "sys", "new")
    assert failed[0][1]["success"] is False
    assert failed[0][1]["error"] == "nats-down"


def test_push_to_alert_center_only_missing_channel_and_success():
    Channel.objects.filter(channel_type="nats").delete()
    alert = _alert()
    missing = AlertLifecycleNotifier().push_to_alert_center_only([alert], "created")
    assert missing == [(alert, False)]

    channel = Channel.objects.create(
        name="center",
        channel_type="nats",
        config={"method_name": "receive_alert_events"},
        description="",
        team=[1],
    )
    with patch.object(
        AlertLifecycleNotifier,
        "_push_to_alert_center",
        return_value=[(alert, {"success": True, "is_alert_center": True})],
    ) as push:
        out = AlertLifecycleNotifier().push_to_alert_center_only([alert], "created", operator="sys")
    push.assert_called_once()
    assert push.call_args.args[0] == channel.id
    assert out == [(alert, True)]
    alert.refresh_from_db()
    assert alert.notice_logs[-1]["success"] is True
