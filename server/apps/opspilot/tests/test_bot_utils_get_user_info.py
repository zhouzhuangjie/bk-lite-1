"""bot_utils.get_user_info：web 直写、企微/钉钉/公众号成功改名与失败回落。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.enum import ChannelChoices
from apps.opspilot.models import Bot, BotChannel, ChannelGroup, ChannelUser, UserGroup
from apps.opspilot.utils.bot_utils import get_user_info

pytestmark = pytest.mark.django_db


def _bot():
    return Bot.objects.create(name="bot-user-info", team=[1])


def test_web_channel_creates_user_with_sender_id_name():
    bot = _bot()
    user, groups = get_user_info(bot.id, "web", "web-sender")
    assert user.user_id == "web-sender"
    assert user.name == "web-sender"
    assert user.channel_type == ChannelChoices.WEB
    assert groups == []
    assert ChannelUser.objects.filter(user_id="web-sender", channel_type=ChannelChoices.WEB).count() == 1


def test_enterprise_wechat_success_creates_groups_and_failure_falls_back():
    bot = _bot()
    BotChannel.objects.create(
        bot=bot,
        name="wecom",
        channel_type=ChannelChoices.ENTERPRISE_WECHAT,
        channel_config={
            "channels.enterprise_wechat_channel.EnterpriseWechatChannel": {
                "corp_id": "corp",
                "secret": "sec",
            }
        },
        enabled=True,
    )
    wechat = MagicMock()
    wechat.user.get.return_value = {"name": "Alice", "department": [9]}
    with patch("apps.opspilot.utils.bot_utils.WeChatClient", return_value=wechat), patch(
        "apps.opspilot.utils.bot_utils.get_enterprise_wechat_user_groups",
        return_value=[{"id": "9", "name": "研发"}],
    ):
        user, groups = get_user_info(bot.id, "enterprise_wechat", "wx-1")
    assert user.name == "Alice"
    assert groups == [{"id": "9", "name": "研发"}]
    assert ChannelGroup.objects.filter(group_id="9", channel_type=ChannelChoices.ENTERPRISE_WECHAT).exists()
    assert UserGroup.objects.filter(user=user).count() == 1

    wechat.user.get.side_effect = RuntimeError("wx down")
    with patch("apps.opspilot.utils.bot_utils.WeChatClient", return_value=wechat):
        failed, failed_groups = get_user_info(bot.id, "enterprise_wechat", "wx-new")
    assert failed.user_id == "wx-new"
    assert failed.name == "wx-new"
    assert failed_groups == []
    assert UserGroup.objects.filter(user=failed).count() == 0


def test_dingtalk_and_official_account_fallback_and_success():
    bot = _bot()
    BotChannel.objects.create(
        bot=bot,
        name="ding",
        channel_type=ChannelChoices.DING_TALK,
        channel_config={
            "channels.dingtalk_channel.DingTalkChannel": {
                "client_id": "id",
                "client_secret": "secret",
            }
        },
        enabled=True,
    )
    BotChannel.objects.create(
        bot=bot,
        name="mp",
        channel_type=ChannelChoices.WECHAT_OFFICIAL_ACCOUNT,
        channel_config={
            "channels.wechat_official_account_channel.WechatOfficialAccountChannel": {
                "appid": "app",
                "secret": "sec",
            }
        },
        enabled=True,
    )

    ding = MagicMock()
    ding.get_user_info.return_value = {"name": "DingUser"}
    with patch("apps.opspilot.utils.bot_utils.DingTalkClient", return_value=ding), patch(
        "apps.opspilot.utils.bot_utils.get_ding_talk_user_groups",
        return_value=[{"id": "d1", "name": "钉钉部"}],
    ):
        user, groups = get_user_info(bot.id, "dingtalk", "ding-1")
    ding.close.assert_called_once()
    assert user.name == "DingUser"
    assert groups[0]["name"] == "钉钉部"

    ding.get_user_info.side_effect = RuntimeError("ding down")
    with patch("apps.opspilot.utils.bot_utils.DingTalkClient", return_value=ding):
        failed, failed_groups = get_user_info(bot.id, "dingtalk", "ding-new")
    assert failed.user_id == "ding-new"
    assert failed.name == "ding-new"
    assert failed_groups == []

    mp = MagicMock()
    mp.user.get.return_value = {"nickname": "Nick", "remark": ""}
    with patch("apps.opspilot.utils.bot_utils.WeChatAccountClient", return_value=mp):
        mp_user, mp_groups = get_user_info(bot.id, "wechat_official_account", "mp-1")
    assert mp_user.name == "Nick"
    assert mp_groups == []

    mp.user.get.side_effect = RuntimeError("mp down")
    with patch("apps.opspilot.utils.bot_utils.WeChatAccountClient", return_value=mp):
        mp_failed, _ = get_user_info(bot.id, "wechat_official_account", "mp-new")
    assert mp_failed.name == "mp-new"
