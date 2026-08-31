"""告警 Notify 基类：用户解析、邮箱与渠道发送。"""
from unittest.mock import patch

import pytest

from apps.alerts.common.notify.notify import Notify

pytestmark = pytest.mark.unit


def test_notify_resolves_users_and_sends_channel_message():
    users = [
        {"id": 1, "username": "alice", "email": "a@example.com"},
        {"id": 2, "username": "bob", "email": "b@example.com"},
    ]
    with patch(
        "apps.alerts.common.notify.notify.SystemMgmtUtils.get_user_all",
        return_value=users,
    ):
        n = Notify(["alice", "missing", "bob"], channel_id=9, title="t", content="c")
    assert n.user_list == [users[0], users[1]]
    assert n.get_user_emails() == ["a@example.com", "b@example.com"]
    with patch(
        "apps.alerts.common.notify.notify.SystemMgmtUtils.send_msg_with_channel",
        return_value={"ok": True},
    ) as send:
        assert n.notify() == {"ok": True}
    send.assert_called_once_with(
        channel_id=9,
        title="t",
        content="c",
        receivers=[1, 2],
    )
