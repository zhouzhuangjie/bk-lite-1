"""node_mgmt 权限 ID/组织归一化：空值、非列表、非法组织 ID 丢弃。"""
import pytest

from apps.node_mgmt.utils.permission import normalize_ids, normalize_orgs

pytestmark = pytest.mark.unit


def test_normalize_ids_stringifies_and_drops_empty():
    assert normalize_ids(None) == []
    assert normalize_ids("") == []
    assert normalize_ids("n-1") == ["n-1"]
    assert normalize_ids([1, "2", None, ""]) == ["1", "2"]


def test_normalize_orgs_keeps_integers_and_skips_garbage():
    assert normalize_orgs(None) == set()
    assert normalize_orgs("3") == {3}
    assert normalize_orgs([1, "2", "x", None]) == {1, 2}
