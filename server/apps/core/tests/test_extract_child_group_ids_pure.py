"""GenericViewSetFun.extract_child_group_ids：命中节点后收集整棵子树。"""
import pytest

from apps.core.utils.viewset_utils import GenericViewSetFun

pytestmark = pytest.mark.unit


def test_extract_child_group_ids_nested_and_missing():
    tree = [
        {
            "id": 1,
            "subGroups": [
                {"id": 2, "subGroups": [{"id": 3}]},
                {"id": 4},
            ],
        },
        {"id": 9},
    ]
    assert GenericViewSetFun.extract_child_group_ids(tree, 1) == [1, 2, 3, 4]
    assert GenericViewSetFun.extract_child_group_ids(tree, 2) == [2, 3]
    assert GenericViewSetFun.extract_child_group_ids(tree, 9) == [9]
    assert GenericViewSetFun.extract_child_group_ids(tree, 99) == []
