"""CMDB init_field_groups：从模型属性提取分组、force 重建、未分组字段回写。"""
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from apps.cmdb.models.field_group import FieldGroup

pytestmark = pytest.mark.django_db


class _Graph:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __init__(self, models, set_calls):
        self._models = models
        self._set_calls = set_calls

    def query_entity(self, *_args, **_kwargs):
        return self._models, 0

    def set_entity_properties(self, *args, **kwargs):
        self._set_calls.append((args, kwargs))


def test_init_field_groups_creates_updates_and_assigns_ungrouped():
    models = [
        {
            "_id": "id-host",
            "model_id": "host",
            "model_name": "主机",
            "attrs": '[{"attr_id":"ip","attr_group":"网络"},{"attr_id":"cpu"}]',
        },
        {"_id": "id-empty", "model_id": "empty", "model_name": "空", "attrs": "[]"},
    ]
    set_calls = []
    FieldGroup.objects.create(model_id="host", group_name="网络", order=9, created_by="old")
    with patch(
        "apps.cmdb.management.commands.init_field_groups.GraphClient",
        side_effect=lambda: _Graph(models, set_calls),
    ), patch(
        "apps.cmdb.management.commands.init_field_groups.ModelManage.parse_attrs",
        side_effect=lambda raw: __import__("json").loads(raw) if raw else [],
    ):
        out = StringIO()
        call_command("init_field_groups", stdout=out)
    text = out.getvalue()
    assert "处理模型数: 1" in text
    assert "跳过模型数: 1" in text
    group = FieldGroup.objects.get(model_id="host", group_name="网络")
    assert "ip" in group.attr_orders
    assert "cpu" in group.attr_orders
    assert set_calls, "未分组字段应写回图属性"


def test_init_field_groups_force_deletes_existing_and_creates_default():
    FieldGroup.objects.create(model_id="switch", group_name="旧分组", created_by="old")
    models = [
        {
            "_id": "id-sw",
            "model_id": "switch",
            "model_name": "交换机",
            "attrs": '[{"attr_id":"port"}]',
        }
    ]
    with patch(
        "apps.cmdb.management.commands.init_field_groups.GraphClient",
        return_value=_Graph(models, []),
    ), patch(
        "apps.cmdb.management.commands.init_field_groups.ModelManage.parse_attrs",
        side_effect=lambda raw: __import__("json").loads(raw),
    ):
        call_command("init_field_groups", force=True)
    names = list(FieldGroup.objects.filter(model_id="switch").values_list("group_name", flat=True))
    assert names == ["默认分组"]
    assert not FieldGroup.objects.filter(group_name="旧分组").exists()
