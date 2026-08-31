"""node_configs 自动注册：企业包缺失、导入失败与无 __path__ 包被跳过。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.cmdb import node_configs as nc

pytestmark = pytest.mark.unit


def test_auto_register_from_package_skips_missing_broken_and_pathless():
    nc._auto_register_from_package("apps.cmdb.node_configs.this_package_is_missing")

    with patch("apps.cmdb.node_configs.importlib.import_module", side_effect=RuntimeError("boom")):
        nc._auto_register_from_package("apps.cmdb.node_configs.cloud")

    with patch("apps.cmdb.node_configs.importlib.import_module", return_value=SimpleNamespace()):
        nc._auto_register_from_package("sys")


def test_import_modules_swallows_individual_failures():
    with patch(
        "apps.cmdb.node_configs.pkgutil.walk_packages",
        return_value=[(None, "pkg._skip", False), (None, "pkg.broken", False)],
    ):
        with patch("apps.cmdb.node_configs.importlib.import_module", side_effect=RuntimeError("nope")):
            nc._import_modules_in_package("pkg", ["/tmp"])


def test_auto_register_node_params_walks_enterprise_packages():
    ext = SimpleNamespace(node_param_packages=["apps.cmdb.enterprise.missing_node_params"])
    with patch("apps.cmdb.collect.extensions.get_collect_enterprise_extension", return_value=ext):
        nc._auto_register_node_params()
