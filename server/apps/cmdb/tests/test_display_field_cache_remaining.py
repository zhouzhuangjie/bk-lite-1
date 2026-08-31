"""排除字段缓存剩余：命中/未命中、异常回退、模型解析失败。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.cmdb.display_field.cache import ExcludeFieldsCache

pytestmark = pytest.mark.unit


def test_initialize_all_success_and_exception():
    with (
        patch.object(ExcludeFieldsCache, "_clear_all_caches") as cleared,
        patch.object(ExcludeFieldsCache, "_refresh_all_caches", return_value=True),
    ):
        assert ExcludeFieldsCache.initialize_all() is True
        cleared.assert_called_once()
    with (
        patch.object(ExcludeFieldsCache, "_clear_all_caches"),
        patch.object(ExcludeFieldsCache, "_refresh_all_caches", return_value=False),
    ):
        assert ExcludeFieldsCache.initialize_all() is False
    with patch.object(ExcludeFieldsCache, "_clear_all_caches", side_effect=RuntimeError("redis down")):
        assert ExcludeFieldsCache.initialize_all() is False


def test_get_or_load_cache_hit_miss_and_exception():
    with patch("apps.cmdb.display_field.cache.cache.get", return_value=["organization"]):
        assert ExcludeFieldsCache.get_exclude_fields() == ["organization"]

    with (
        patch("apps.cmdb.display_field.cache.cache.get", side_effect=[None, {"host": {}}]),
        patch.object(ExcludeFieldsCache, "_refresh_all_caches") as refresh,
    ):
        assert ExcludeFieldsCache.get_model_fields_mapping() == {"host": {}}
        refresh.assert_called_once()

    with patch("apps.cmdb.display_field.cache.cache.get", side_effect=RuntimeError("down")):
        assert ExcludeFieldsCache.get_exclude_fields() == []


def test_update_on_model_change_and_cache_info_error():
    with patch.object(ExcludeFieldsCache, "_refresh_all_caches", return_value=True):
        assert ExcludeFieldsCache.update_on_model_change("host") is True
    with patch.object(ExcludeFieldsCache, "_refresh_all_caches", return_value=False):
        assert ExcludeFieldsCache.update_on_model_change("host") is False
    with patch.object(ExcludeFieldsCache, "_refresh_all_caches", side_effect=RuntimeError("down")):
        assert ExcludeFieldsCache.update_on_model_change("host") is False

    with patch("apps.cmdb.display_field.cache.cache.get", side_effect=RuntimeError("down")):
        info = ExcludeFieldsCache.get_cache_info()
    assert info["exclude_fields"]["is_cached"] is False
    assert info["exclude_fields"]["error"] == "down"


def test_refresh_clear_load_and_build_helpers():
    with patch.object(ExcludeFieldsCache, "_load_models_from_db", side_effect=RuntimeError("db")):
        assert ExcludeFieldsCache._refresh_all_caches() is False

    cache_backend = MagicMock()
    cache_backend.delete_pattern = MagicMock()
    with patch("apps.cmdb.display_field.cache.cache", cache_backend):
        assert ExcludeFieldsCache._clear_all_caches() is True
        cache_backend.delete_pattern.assert_called()
    with patch("apps.cmdb.display_field.cache.cache.delete", side_effect=RuntimeError("down")):
        assert ExcludeFieldsCache._clear_all_caches() is False

    graph = MagicMock()
    graph.__enter__.return_value = graph
    graph.__exit__.return_value = False
    graph.query_entity.side_effect = RuntimeError("graph down")
    with patch("apps.cmdb.display_field.cache.GraphClient", return_value=graph):
        assert ExcludeFieldsCache._load_models_from_db() == []

    with patch("apps.cmdb.services.model.ModelManage.parse_attrs", side_effect=ValueError("bad json")):
        assert ExcludeFieldsCache._build_exclude_fields([{"model_id": "host", "attrs": "{"}]) == []
        mapping = ExcludeFieldsCache._build_model_fields_mapping([{"model_id": "host", "attrs": "{" }])
        assert mapping == {}

    with patch("apps.cmdb.display_field.cache.cache.set", side_effect=RuntimeError("down")):
        assert ExcludeFieldsCache._save_cache("k", []) is False
    with patch("apps.cmdb.display_field.cache.cache.set"):
        assert ExcludeFieldsCache._save_cache("k", ["organization"]) is True
