"""日志策略：无当前团队时不查权限，并缓存空结果。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.log.views import policy as policy_views

pytestmark = pytest.mark.unit


def test_to_positive_int_clamps_and_falls_back():
    assert policy_views._to_positive_int("8", 1) == 8
    assert policy_views._to_positive_int("abc", 4) == 4
    assert policy_views._to_positive_int("0", 1, min_val=1, max_val=10) == 1
    assert policy_views._to_positive_int("99", 1, min_val=1, max_val=10) == 10


def test_accessible_log_policy_ids_empty_team_is_cached():
    request = SimpleNamespace(user=SimpleNamespace(username="u"), COOKIES={})
    with (
        patch("apps.log.views.policy.get_current_team", return_value=None) as team,
        patch("apps.log.views.policy.get_permissions_rules") as perms,
    ):
        first = policy_views.get_accessible_log_policy_ids(request)
        second = policy_views.get_accessible_log_policy_ids(request)
    assert first == []
    assert second == []
    team.assert_called_once()
    perms.assert_not_called()


def test_accessible_log_policy_ids_empty_when_permissions_not_dict():
    request = SimpleNamespace(user=SimpleNamespace(username="u"), COOKIES={})
    with (
        patch("apps.log.views.policy.get_current_team", return_value=1),
        patch("apps.log.views.policy.get_permissions_rules", return_value=["not-a-dict"]),
    ):
        assert policy_views.get_accessible_log_policy_ids(request, collect_type_id="all") == []
        # 缓存命中，不再查询权限
        with patch("apps.log.views.policy.get_permissions_rules") as perms:
            assert policy_views.get_accessible_log_policy_ids(request, collect_type_id="all") == []
        perms.assert_not_called()


def test_get_permission_context_coerces_non_dict():
    request = SimpleNamespace(user=SimpleNamespace(username="u"), COOKIES={})
    with (
        patch("apps.log.views.policy.get_current_team", return_value=1),
        patch("apps.log.views.policy.get_permissions_rules", return_value="bad"),
    ):
        data, teams = policy_views.PolicyViewSet()._get_permission_context(request)
    assert data == {}
    assert teams == set()


def test_accessible_log_policy_ids_empty_when_policy_permissions_missing():
    request = SimpleNamespace(user=SimpleNamespace(username="u"), COOKIES={})
    with (
        patch("apps.log.views.policy.get_current_team", return_value=1),
        patch("apps.log.views.policy.get_permissions_rules", return_value={"data": {}, "team": [1]}),
    ):
        assert policy_views.get_accessible_log_policy_ids(request) == []
