"""CMDB NATS：变更趋势缺参、时间分桶；模型实例 TOP；权威映射。"""
import pytest
from django.utils import timezone as dj_tz

from apps.cmdb.models.change_record import CREATE_INST, ChangeRecord, UPDATE_INST
from apps.cmdb.nats import nats as N
from apps.system_mgmt.models import Group, User as SysUser

pytestmark = pytest.mark.django_db


def test_get_change_trend_requires_time_range():
    result = N.get_change_trend(time=None)
    assert result["result"] is False
    assert "time parameter" in result["message"]
    result = N.get_change_trend(time=["only-one"])
    assert result["result"] is False


def test_get_change_trend_groups_create_and_update():
    ChangeRecord.objects.create(
        inst_id=1, model_id="host", label="l", type=CREATE_INST, operator="u", message="c"
    )
    ChangeRecord.objects.create(
        inst_id=2, model_id="host", label="l", type=UPDATE_INST, operator="u", message="u"
    )
    now = dj_tz.now()
    start = (now.replace(hour=0, minute=0, second=0, microsecond=0)).strftime("%Y-%m-%d %H:%M:%S")
    end = "2099-01-01 00:00:00"
    result = N.get_change_trend(time=[start, end], group_by="day", model_id="host")
    assert result["result"] is True
    assert "创建" in result["data"]
    assert "修改" in result["data"]
    create_total = sum(item[1] for item in result["data"]["创建"])
    update_total = sum(item[1] for item in result["data"]["修改"])
    assert create_total >= 1
    assert update_total >= 1


def test_get_cmdb_model_instance_top_sorts_and_filters(monkeypatch):
    monkeypatch.setattr(N, "_build_nats_model_permission_map", lambda user_info: {})
    monkeypatch.setattr(N, "_build_nats_permission_map", lambda user_info: {})
    monkeypatch.setattr(
        "apps.cmdb.nats.nats.ClassificationManage.search_model_classification",
        lambda: [
            {"classification_id": "infra", "classification_name": "基础设施"},
            {"classification_id": "app", "classification_name": "应用"},
        ],
    )
    monkeypatch.setattr(
        "apps.cmdb.nats.nats.ModelManage.search_model",
        lambda permissions_map=None: [
            {"model_id": "host", "model_name": "主机", "classification_id": "infra"},
            {"model_id": "app", "model_name": "应用", "classification_id": "app"},
            {"model_id": "switch", "model_name": "交换机", "classification_id": "infra"},
        ],
    )
    monkeypatch.setattr(
        "apps.cmdb.nats.nats.InstanceManage.model_inst_count",
        lambda permissions_map=None: {"host": 9, "app": 3, "switch": 9},
    )
    result = N.get_cmdb_model_instance_top(limit=2, classification_id="infra")
    assert result["result"] is True
    assert [row["model_id"] for row in result["data"]] == ["host", "switch"]
    assert result["data"][0]["count"] == 9
    assert result["data"][0]["classification"] == "基础设施"

    monkeypatch.setattr(N, "_build_nats_model_permission_map", lambda user_info: None)
    empty = N.get_cmdb_model_instance_top()
    assert empty["data"] == []


def test_build_authoritative_maps_resolves_org_user_enum():
    group = Group.objects.create(name="org-a")
    user = SysUser.objects.create(
        username="map-user", display_name="映射用户", email="m@example.com", password="x", domain="domain.com"
    )
    instances = [{"org": [group.id], "owner": user.id, "status": "1"}]
    attrs = [
        {"attr_id": "org", "attr_type": N.FIELD_TYPE_ORGANIZATION, "is_display_field": False},
        {"attr_id": "owner", "attr_type": N.FIELD_TYPE_USER, "is_display_field": False},
        {
            "attr_id": "status",
            "attr_type": N.FIELD_TYPE_ENUM,
            "is_display_field": False,
            "option": [{"id": "1", "name": "在线"}],
        },
        {"attr_id": "skip", "attr_type": N.FIELD_TYPE_USER, "is_display_field": True},
    ]
    group_map, user_map, enum_map = N._build_authoritative_maps(instances, attrs)
    assert group_map[group.id] == "org-a"
    assert user_map[user.id]["username"] == "map-user"
    assert enum_map["status"]["1"] == "在线"
    formatted = N._format_user_value(user.id, user_map)
    assert "映射用户" in formatted or formatted == "map-user"
