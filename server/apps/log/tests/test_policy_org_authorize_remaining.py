"""日志策略组织授权：范围合并与 403 文案。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.log.views.policy import PolicyViewSet

pytestmark = pytest.mark.unit


def test_allowed_organization_scope_merges_all_and_type():
    vs = PolicyViewSet()
    data = {
        "all": {"team": [1, "2"]},
        "5": {"team": [7]},
        "6": {"team": ["bad", 8]},
        "skip": "not-dict",
    }
    assert vs._allowed_organization_scope(data, [3], collect_type_id=5) == {1, 2, 3, 7}
    merged = vs._allowed_organization_scope(data, [3], collect_type_id=None)
    assert merged == {1, 2, 3, 7, 8}


def test_authorize_policy_and_target_orgs_return_403():
    vs = PolicyViewSet()
    req = SimpleNamespace()
    instance = SimpleNamespace()
    with patch.object(vs, "_get_permission_context", return_value=({}, [1])):
        with patch.object(vs, "_permissions_for_policy", return_value=set()):
            resp = vs._authorize_policy(req, instance)
    assert resp.status_code == 403
    assert b"User does not have permission to operate this policy" in resp.content

    with patch.object(vs, "_get_permission_context", return_value=({"all": {"team": [1]}}, [1])):
        assert vs._authorize_target_organizations(req, []) is None
        resp = vs._authorize_target_organizations(req, [1, 9], collect_type_id=None)
    assert resp.status_code == 403
    assert b"User does not have permission to assign policies to these organizations" in resp.content
