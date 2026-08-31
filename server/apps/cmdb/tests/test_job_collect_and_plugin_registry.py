"""JobCollect 路由、采集插件注册覆盖/冲突，以及 loader 包导入失败契约。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.cmdb.collection.collect_tasks.job_collect import JobCollect
from apps.cmdb.collection.plugins.loader import CollectionPluginLoader
from apps.cmdb.collection.plugins.registry import CollectionPluginRegistry
from apps.cmdb.constants.constants import CollectPluginTypes

pytestmark = pytest.mark.unit


def test_job_collect_routes_task_type_and_empty_instance():
    empty = JobCollect(SimpleNamespace(instances=[], id=3, task_type=CollectPluginTypes.HOST))
    assert empty.get_instance() is None

    task = SimpleNamespace(instances=[{"ip": "10.0.0.1"}], id=8, task_type=CollectPluginTypes.HOST)
    jc = JobCollect(task, default_metrics=["up"])
    assert jc.get_instance() == {"ip": "10.0.0.1"}
    assert jc.collect_manage[CollectPluginTypes.HOST] == jc.collect_host
    assert jc.collect_manage[CollectPluginTypes.DB] == jc.collect_db
    assert jc.collect_manage[CollectPluginTypes.MIDDLEWARE] == jc.collect_middleware
    assert jc.collect_manage[CollectPluginTypes.CONFIG_FILE] == jc.collect_config_file

    class _Callable:
        def __init__(self, *a, **k):
            self.args = a
            self.kwargs = k

        def __call__(self):
            return {"via": self.__class__.__name__, "task_id": self.args[0]}

    with patch("apps.cmdb.collection.collect_tasks.job_collect.HostCollect", _Callable):
        assert jc.collect_host() == {"via": "_Callable", "task_id": 8}
    with patch("apps.cmdb.collection.collect_tasks.job_collect.DBCollect", _Callable):
        assert jc.collect_db() == {"via": "_Callable", "task_id": 8}
    with patch("apps.cmdb.collection.collect_tasks.job_collect.MiddlewareCollect", _Callable):
        assert jc.collect_middleware() == {"via": "_Callable", "task_id": 8}
    with patch("apps.cmdb.collection.collect_tasks.job_collect.ConfigFileCollect", _Callable):
        assert jc.collect_config_file() == {"via": "_Callable", "task_id": 8}

    with patch.object(jc, "collect_host", return_value={"hosts": 1}):
        assert jc.main() == {"hosts": 1}


def test_collection_plugin_registry_override_conflict_and_lookup():
    saved_registry = CollectionPluginRegistry._registry
    saved_init = CollectionPluginRegistry._initialized
    CollectionPluginRegistry._registry = {}
    CollectionPluginRegistry._initialized = True
    try:

        class Incomplete:
            supported_task_type = ""
            supported_model_id = "host"

        CollectionPluginRegistry.register(Incomplete)

        class Low:
            supported_task_type = "host"
            supported_model_id = "host"
            priority = 1
            plugin_source = "community"

        class High:
            supported_task_type = "host"
            supported_model_id = "host"
            priority = 5
            plugin_source = "enterprise"

        class Same:
            supported_task_type = "host"
            supported_model_id = "host"
            priority = 5
            plugin_source = "other"

        CollectionPluginRegistry.register(Low)
        CollectionPluginRegistry.register(High)
        CollectionPluginRegistry.register(Same)
        assert CollectionPluginRegistry.get_plugin("host", "host") is High
        with pytest.raises(ValueError, match="Unsupported collection plugin: task_type=db, model_id=mysql"):
            CollectionPluginRegistry.get_plugin("db", "mysql")
        snap = CollectionPluginRegistry.get_registry_snapshot()
        assert snap == [
            {
                "task_type": "host",
                "model_id": "host",
                "class_name": "High",
                "module": High.__module__,
                "plugin_source": "enterprise",
                "priority": 5,
            }
        ]
    finally:
        CollectionPluginRegistry._registry = saved_registry
        CollectionPluginRegistry._initialized = saved_init


def test_collection_plugin_loader_skips_loaded_and_handles_import_failures():
    saved_loaded = CollectionPluginLoader._loaded
    CollectionPluginLoader._loaded = True
    try:
        assert CollectionPluginLoader.load_plugins() is True
    finally:
        CollectionPluginLoader._loaded = saved_loaded

    assert CollectionPluginLoader._load_package("apps.cmdb.this_package_does_not_exist") is True

    def boom_other(name):
        err = ModuleNotFoundError("missing dep")
        err.name = "some.other.dep"
        raise err

    with patch("apps.cmdb.collection.plugins.loader.importlib.import_module", side_effect=boom_other):
        assert CollectionPluginLoader._load_package("apps.cmdb.collection.plugins.community") is False

    with patch("apps.cmdb.collection.plugins.loader.importlib.import_module", side_effect=RuntimeError("broken")):
        assert CollectionPluginLoader._load_package("apps.cmdb.collection.plugins.community") is False

    walked = [(None, "pkg._hidden", False), (None, "pkg.real", False)]
    imported = []

    def import_mod(name):
        imported.append(name)
        if name == "pkg.real":
            raise RuntimeError("plugin broken")
        return SimpleNamespace(__path__=["/tmp/not-a-real-plugin-path"])

    with patch("apps.cmdb.collection.plugins.loader.pkgutil.walk_packages", return_value=walked):
        with patch("apps.cmdb.collection.plugins.loader.importlib.import_module", side_effect=import_mod):
            assert CollectionPluginLoader._load_package("pkg") is False
    assert imported == ["pkg", "pkg.real"]

    no_path = SimpleNamespace()
    with patch("apps.cmdb.collection.plugins.loader.importlib.import_module", return_value=no_path):
        assert CollectionPluginLoader._load_package("sys") is True
