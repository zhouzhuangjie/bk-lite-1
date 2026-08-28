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
