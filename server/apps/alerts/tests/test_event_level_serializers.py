"""告警 Event/Level 序列化器：团队授权与等级唯一性。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError

from apps.alerts.models.models import Level
from apps.alerts.serializers.event import EventModelSerializer
from apps.alerts.serializers.level import LevelModelSerializer

pytestmark = pytest.mark.django_db


def test_event_validate_team_superuser_and_unauthorized():
    none_req = SimpleNamespace(context={"request": None})
    assert EventModelSerializer.validate_team(none_req, ["1", 2]) == [1, 2]

    su = SimpleNamespace(context={"request": SimpleNamespace(user=SimpleNamespace(is_superuser=True))})
    assert EventModelSerializer.validate_team(su, [3]) == [3]

    req = SimpleNamespace(context={"request": SimpleNamespace(user=SimpleNamespace(is_superuser=False))})
    with patch("apps.alerts.serializers.event.get_authorized_group_ids", return_value=[1]):
        with pytest.raises(ValidationError, match="You are not authorized to assign teams"):
            EventModelSerializer.validate_team(req, [1, 9])


def test_level_serializer_rejects_negative_long_icon_and_duplicate():
    ser = LevelModelSerializer()
    with pytest.raises(ValidationError, match="等级值不能为空"):
        ser.validate_level_id(None)
    with pytest.raises(ValidationError, match="等级值必须为非负整数"):
        ser.validate_level_id(-1)
    assert ser.validate_level_id(0) == 0
    assert ser.validate_icon("") == ""
    assert ser.validate_icon("data:image/png;base64,abc") == "data:image/png;base64,abc"
    with pytest.raises(ValidationError, match="默认图标标识过长"):
        ser.validate_icon("x" * 101)

    Level.objects.create(level_id=901, level_type="alert", level_name="p901", level_display_name="P901")
    with pytest.raises(ValidationError) as exc:
        LevelModelSerializer().validate({"level_type": "alert", "level_id": 901})
    detail = exc.value.detail["level_id"]
    assert str(detail[0] if isinstance(detail, list) else detail) == "同类型下等级值已存在。"

    inst = Level.objects.create(level_id=902, level_type="alert", level_name="p902", level_display_name="P902")
    with pytest.raises(ValidationError) as exc:
        LevelModelSerializer(instance=inst).validate({"level_id": 3})
    detail = exc.value.detail["level_id"]
    assert str(detail[0] if isinstance(detail, list) else detail) == "等级值创建后不允许修改。"
    with pytest.raises(ValidationError) as exc:
        LevelModelSerializer(instance=inst).validate({"level_type": "event"})
    detail = exc.value.detail["level_type"]
    assert str(detail[0] if isinstance(detail, list) else detail) == "等级类型创建后不允许修改。"
