"""DisplayFieldHandler.get_all_exclude_fields：聚合各模型 organization/user/enum 字段。"""
from unittest.mock import MagicMock

import pytest

from apps.cmdb.display_field.handler import DisplayFieldHandler

pytestmark = pytest.mark.unit


def test_get_all_exclude_fields_merges_and_sorts(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.query_entity.return_value = (
        [
            {"model_id": "host", "attrs": "[]"},
            {"model_id": "app", "attrs": "[]"},
        ],
        None,
    )
    monkeypatch.setattr("apps.cmdb.display_field.handler.GraphClient", lambda: client)
    monkeypatch.setattr(
        "apps.cmdb.services.model.ModelManage.parse_attrs",
        lambda raw: [{"attr_id": "org"}, {"attr_id": "owner"}],
    )
    monkeypatch.setattr(
        DisplayFieldHandler,
        "get_exclude_fields_from_attrs",
        classmethod(lambda cls, attrs: [item["attr_id"] for item in attrs] + (["status"] if attrs else [])),
    )
    result = DisplayFieldHandler.get_all_exclude_fields()
    assert result == ["org", "owner", "status"]


def test_get_all_exclude_fields_returns_empty_on_graph_error(monkeypatch):
    class Boom:
        def __enter__(self):
            raise RuntimeError("graph down")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("apps.cmdb.display_field.handler.GraphClient", Boom)
    assert DisplayFieldHandler.get_all_exclude_fields() == []
