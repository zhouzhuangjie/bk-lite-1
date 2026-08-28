"""CMDB NATS 处理器纯辅助函数覆盖测试。

对照 spec/prd/CMDB·资产/运营分析取数：资产实例展示格式化、变更趋势时间分桶。
"""

import datetime
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.cmdb.nats import nats as N


# --------------------------------------------------------------------------
# _normalize_to_list
# --------------------------------------------------------------------------


def test_normalize_to_list_variants():
    assert N._normalize_to_list(None) == []
    assert N._normalize_to_list("") == []
    assert N._normalize_to_list([1, None, 2, ""]) == [1, 2]
    assert N._normalize_to_list("x") == ["x"]


# --------------------------------------------------------------------------
# _normalize_permission_user
# --------------------------------------------------------------------------


def test_normalize_permission_user_obj():
    user = SimpleNamespace(username="u", domain="domain.com")
    assert N._normalize_permission_user(user) is user


def test_normalize_permission_user_str():
    out = N._normalize_permission_user("alice", domain="domain.com")
    assert out.username == "alice"
    assert out.domain == "domain.com"


# --------------------------------------------------------------------------
# _format_user_value
# --------------------------------------------------------------------------


def test_format_user_value_with_display():
    m = {1: {"username": "u1", "display_name": "用户1"}}
    assert N._format_user_value(1, m) == "用户1(u1)"


def test_format_user_value_no_display():
    m = {1: {"username": "u1", "display_name": ""}}
    assert N._format_user_value(1, m) == "u1"


def test_format_user_value_unknown():
    assert N._format_user_value(99, {}) == "99"


# --------------------------------------------------------------------------
# _get_trunc_func_and_format
# --------------------------------------------------------------------------


def test_get_trunc_func_and_format():
    from django.db.models.functions import TruncDate, TruncHour, TruncMonth

    assert N._get_trunc_func_and_format("hour")[0] is TruncHour
    assert N._get_trunc_func_and_format("month")[0] is TruncMonth
    assert N._get_trunc_func_and_format("unknown")[0] is TruncDate


# --------------------------------------------------------------------------
# _resolve_target_timezone / _parse_client_datetime / _format_period_value
# --------------------------------------------------------------------------


def test_resolve_target_timezone_valid():
    assert N._resolve_target_timezone("Asia/Shanghai") is not None


def test_resolve_target_timezone_invalid():
    assert N._resolve_target_timezone("Bad/Zone") == timezone.get_current_timezone()


def test_parse_client_datetime_iso():
    tz = timezone.get_current_timezone()
    assert isinstance(N._parse_client_datetime("2026-01-01T00:00:00Z", tz), datetime.datetime)


def test_parse_client_datetime_plain():
    tz = timezone.get_current_timezone()
    assert isinstance(N._parse_client_datetime("2026-01-01 00:00:00", tz), datetime.datetime)


def test_format_period_value_date():
    tz = timezone.get_current_timezone()
    assert "2026-01-01" in N._format_period_value(datetime.date(2026, 1, 1), tz)


# --------------------------------------------------------------------------
# _generate_time_periods
# --------------------------------------------------------------------------


def test_generate_time_periods_day():
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.datetime(2026, 1, 1), tz)
    end = timezone.make_aware(datetime.datetime(2026, 1, 3), tz)
    assert len(N._generate_time_periods(start, end, "day", tz)) == 3


def test_generate_time_periods_hour():
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.datetime(2026, 1, 1, 0), tz)
    end = timezone.make_aware(datetime.datetime(2026, 1, 1, 3), tz)
    assert len(N._generate_time_periods(start, end, "hour", tz)) == 3


def test_generate_time_periods_month():
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.datetime(2026, 1, 1), tz)
    end = timezone.make_aware(datetime.datetime(2026, 4, 1), tz)
    assert len(N._generate_time_periods(start, end, "month", tz)) >= 3


# --------------------------------------------------------------------------
# _format_instance_for_asset_query
# --------------------------------------------------------------------------


def test_format_instance_for_asset_query_org_user_enum():
    attrs = [
        {"attr_id": "org", "attr_type": "organization"},
        {"attr_id": "owner", "attr_type": "user"},
        {"attr_id": "level", "attr_type": "enum"},
        {"attr_id": "name", "attr_type": "str"},
    ]
    instance = {"org": [1], "owner": [10], "level": "a", "name": "host1"}
    group_name_map = {1: "总部"}
    user_info_map = {10: {"username": "u1", "display_name": "用户1"}}
    enum_name_maps = {"level": {"a": "高"}}
    out = N._format_instance_for_asset_query(instance, attrs, group_name_map, user_info_map, enum_name_maps)
    assert out["org"] == "总部"
    assert out["owner"] == "用户1(u1)"
    assert out["level"] == "高"
    assert out["name"] == "host1"


def test_format_instance_skips_display_suffix_and_formats_tag_table():
    attrs = [
        {"attr_id": "tags", "attr_type": "tag"},
        {"attr_id": "table", "attr_type": "table"},
        {"attr_id": "level", "attr_type": "enum"},
    ]
    instance = {
        "tags": ["env:prod", "app:web"],
        "table": [{"col": "a"}],
        "level": ["a", "b"],
        "name_display": "hidden",
        "plain": "keep",
    }
    out = N._format_instance_for_asset_query(
        instance, attrs, {}, {}, {"level": {"a": "高", "b": "中"}}
    )
    assert "name_display" not in out
    assert "prod" in out["tags"] and "web" in out["tags"]
    assert out["level"] == "高, 中"
    assert out["plain"] == "keep"


def test_format_asset_instances_response_empty():
    assert N._format_asset_instances_response("host", []) == []


def test_parse_nats_datetime_empty_and_iso():
    assert N._parse_nats_datetime(None) is None
    assert N._parse_nats_datetime("") is None
    assert isinstance(N._parse_nats_datetime("2026-01-01T00:00:00Z"), datetime.datetime)


def test_generate_time_periods_week():
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.datetime(2026, 1, 5), tz)  # Monday
    end = timezone.make_aware(datetime.datetime(2026, 1, 20), tz)
    weeks = N._generate_time_periods(start, end, "week", tz)
    assert len(weeks) >= 2


def test_get_authorized_team_ids_admin_and_normal(monkeypatch):
    admin = SimpleNamespace(group_list=[1], role_list=[9])
    monkeypatch.setattr(
        N.Role.objects,
        "filter",
        lambda **kwargs: SimpleNamespace(only=lambda *a: [SimpleNamespace(app="", name="admin")]),
    )
    monkeypatch.setattr(N.GroupUtils, "get_group_with_descendants", lambda team: [team, 2])
    assert N._get_authorized_team_ids(admin, 1, include_children=True) == [1, 2]

    user = SimpleNamespace(group_list=[{"id": 3}], role_list=[])
    monkeypatch.setattr(
        N.GroupUtils,
        "get_user_authorized_child_groups",
        lambda **kwargs: [3],
    )
    assert N._get_authorized_team_ids(user, 3, include_children=False) == [3]


def test_get_cmdb_module_data_unknown_and_missing_user():
    with pytest.raises(ValueError, match="Invalid module type"):
        N.get_cmdb_module_data("nope", "x", 1, 10, 1, user_info=None)
    empty = N.get_cmdb_module_data("instances", "host", 1, 10, 1, user_info=None)
    assert empty == {"count": 0, "items": []}

