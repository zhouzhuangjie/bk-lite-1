"""Sidecar：模板渲染跳过密码、节点变量、子配置 env 过滤。"""
from types import SimpleNamespace

import pytest

from apps.node_mgmt.services.sidecar import Sidecar

pytestmark = pytest.mark.unit


def test_render_template_rewrites_node_dot_and_skips_password():
    rendered = Sidecar.render_template(
        "id=${node.id} ip=${node.ip} pwd=${password} keep=${keep}",
        {"node__id": "n1", "node__ip": "10.0.0.1", "password": "secret", "NATS_PASSWORD": "also", "keep": "ok"},
    )
    assert rendered == "id=n1 ip=10.0.0.1 pwd=${password} keep=ok"
    assert "secret" not in rendered
    assert "also" not in rendered


def test_collect_child_render_variables_skips_dunder_keys():
    children = [
        SimpleNamespace(env_config={"HOST": "h1", "nested__key": "skip", "PORT": "22"}),
        SimpleNamespace(env_config=None),
        SimpleNamespace(env_config={"HOST": "h2"}),
    ]
    assert Sidecar.collect_child_render_variables(children) == {"HOST": "h2", "PORT": "22"}


def test_get_variables_merges_region_env_and_node_fields():
    node = SimpleNamespace(
        id="node-9",
        cloud_region_id=3,
        name="edge",
        ip="10.1.2.3",
        operating_system="linux",
        collector_configuration_directory="/etc/sidecar",
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Sidecar, "get_cloud_region_envconfig", lambda n: {"NATS_URL": "nats://x"})
        variables = Sidecar.get_variables(node)
    assert variables["NATS_URL"] == "nats://x"
    assert variables["node__id"] == "node-9"
    assert variables["node__cloud_region"] == 3
    assert variables["node__name"] == "edge"
    assert variables["node__ip"] == "10.1.2.3"
    assert variables["node__ip_filter"] == "10-1-2-3"
    assert variables["node__operating_system"] == "linux"
    assert variables["PACKETBEAT_DEVICE"] == "any"

    node.operating_system = "windows"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Sidecar, "get_cloud_region_envconfig", lambda n: {})
        win = Sidecar.get_variables(node)
    assert win["PACKETBEAT_DEVICE"] == "0"
