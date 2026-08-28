"""日志策略：组织 payload 规范化与 crontab 调度映射。"""
import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.log.views.policy import PolicyViewSet

pytestmark = pytest.mark.django_db


def test_normalize_orgs_skips_invalid_and_accepts_scalar():
    assert PolicyViewSet._normalize_orgs(None) == set()
    assert PolicyViewSet._normalize_orgs([]) == set()
    assert PolicyViewSet._normalize_orgs("3") == {3}
    assert PolicyViewSet._normalize_orgs(["1", 2, "x", None]) == {1, 2}


def test_validate_organizations_payload_required_and_dedupes():
    normalized, err = PolicyViewSet._validate_organizations_payload(None)
    assert normalized == []
    assert err is None
    _, err = PolicyViewSet._validate_organizations_payload("1")
    assert err is not None
    _, err = PolicyViewSet._validate_organizations_payload([True])
    assert err is not None
    _, err = PolicyViewSet._validate_organizations_payload(["ab"])
    assert err is not None
    _, err = PolicyViewSet._validate_organizations_payload([], required=True)
    assert err is not None
    normalized, err = PolicyViewSet._validate_organizations_payload(["1", 1, 2])
    assert err is None
    assert normalized == [1, 2]


def test_format_crontab_min_hour_day_and_invalid():
    view = PolicyViewSet()
    minute = view.format_crontab({"type": "min", "value": 5})
    assert minute.minute == "*/5"
    hour = view.format_crontab({"type": "hour", "value": 2})
    assert hour.hour == "*/2"
    day = view.format_crontab({"type": "day", "value": 3})
    assert day.day_of_month == "*/3"
    with pytest.raises(BaseAppException):
        view.format_crontab({"type": "week", "value": 1})
