"""Sidecar.get_node_config / get_node_config_env：ETag 304、子配置分段渲染、密码解密。"""
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from apps.node_mgmt.constants.node import NodeConstants
from apps.node_mgmt.models import Collector, Node
from apps.node_mgmt.models.cloud_region import CloudRegion
from apps.node_mgmt.models.sidecar import ChildConfig, CollectorConfiguration
from apps.node_mgmt.services.sidecar import Sidecar
from apps.node_mgmt.services.sidecar_cache import build_configuration_etag_cache_key

pytestmark = pytest.mark.django_db


def _request(headers=None, meta=None):
    req = MagicMock()
    req.headers = headers or {}
    req.META = meta or {}
    return req


def _setup_bound_config(node, *, template="listen: ${HOST}", env=None, default_config=None, name=None):
    suffix = name or uuid.uuid4().hex[:8]
    collector = Collector.objects.create(
        id=f"c-{suffix}",
        name=f"C-{suffix}",
        service_type="svc",
        node_operating_system="linux",
        executable_path="/bin",
        execute_parameters="-c",
        default_config=default_config or {},
    )
    config = CollectorConfiguration.objects.create(
        name=f"cfg-{suffix}",
        collector=collector,
        cloud_region=node.cloud_region,
        config_template=template,
        env_config=env or {},
    )
    config.nodes.add(node)
    return config


@pytest.fixture
def node():
    suffix = uuid.uuid4().hex[:8]
    region = CloudRegion.objects.create(name=f"cr-cfg-{suffix}")
    return Node.objects.create(
        id=f"node-cfg-{suffix}",
        name="edge",
        ip="10.8.8.8",
        operating_system="linux",
        collector_configuration_directory="/etc/sidecar",
        cloud_region=region,
    )


def test_get_node_config_etag_hit_returns_304_when_bound(node):
    config = _setup_bound_config(node, name="etag-hit")
    cache_key = build_configuration_etag_cache_key(node.id, config.id)
    req = _request(headers={"If-None-Match": '"etag-hit"'})
    with patch("apps.node_mgmt.services.sidecar.cache.get", return_value="etag-hit") as cache_get:
        resp = Sidecar.get_node_config(req, node.id, config.id)
    cache_get.assert_called_once_with(cache_key)
    assert resp.status_code == 304
    assert resp["ETag"] == "etag-hit"


def test_get_node_config_etag_hit_unbound_returns_404(node):
    suffix = uuid.uuid4().hex[:8]
    collector = Collector.objects.create(
        id=f"c-unbound-{suffix}",
        name=f"C-unbound-{suffix}",
        service_type="svc",
        node_operating_system="linux",
        executable_path="/bin",
        execute_parameters="-c",
    )
    config = CollectorConfiguration.objects.create(
        name=f"cfg-unbound-{suffix}",
        collector=collector,
        cloud_region=node.cloud_region,
    )
    req = _request(headers={"If-None-Match": "stale"})
    with patch("apps.node_mgmt.services.sidecar.cache.get", return_value="stale"):
        resp = Sidecar.get_node_config(req, node.id, config.id)
    assert resp.status_code == 404
    assert json.loads(resp.content)["error"] == "Configuration not found"


def test_get_node_config_renders_grouped_and_ungrouped_children(node):
    config = _setup_bound_config(
        node,
        template="base: ${KEEP}\n",
        env={"KEEP": "ok", "HOST": "from-parent"},
        default_config={"config_section": {"inputs": "\n[inputs]\n"}},
        name="children",
    )
    ChildConfig.objects.create(
        collect_type="cpu",
        config_type="telegraf",
        content="cpu_host=${HOST}",
        collector_config=config,
        env_config={"HOST": "child-host"},
        config_section="inputs",
        sort_order=1,
    )
    ChildConfig.objects.create(
        collect_type="disk",
        config_type="telegraf",
        content="disk_only",
        collector_config=config,
        env_config={},
        config_section="",
        sort_order=2,
    )
    req = _request()
    with patch.object(Sidecar, "get_cloud_region_envconfig", return_value={}), patch(
        "apps.node_mgmt.services.sidecar.cache.set"
    ) as cache_set:
        resp = Sidecar.get_node_config(req, node.id, config.id)
    body = json.loads(resp.content)
    assert body["id"] == config.id
    assert "base: ok" in body["template"]
    assert "[inputs]" in body["template"]
    assert "# cpu - telegraf" in body["template"]
    assert "cpu_host=child-host" in body["template"]
    assert "# disk - telegraf" in body["template"]
    assert "disk_only" in body["template"]
    assert resp["ETag"]
    cache_set.assert_called_once()


def test_get_node_config_plain_children_without_section_headers(node):
    config = _setup_bound_config(node, template="root\n", name="plain")
    ChildConfig.objects.create(
        collect_type="log",
        config_type="file",
        content="path=/var/log",
        collector_config=config,
        env_config={"nested__skip": "x", "VISIBLE": "1"},
    )
    req = _request()
    with patch.object(Sidecar, "get_cloud_region_envconfig", return_value={}):
        resp = Sidecar.get_node_config(req, node.id, config.id)
    body = json.loads(resp.content)
    assert body["template"] == "root\n\n# log - file\npath=/var/log"


def test_get_node_config_env_merges_decrypts_and_falls_back(node):
    config = _setup_bound_config(
        node,
        env={"DB_PASSWORD": "enc-parent", "PLAIN": "keep"},
        name="env",
    )
    ChildConfig.objects.create(
        collect_type="db",
        config_type="mysql",
        content="",
        collector_config=config,
        env_config={"DB_PASSWORD": "enc-child", "EXTRA": 12},
    )
    req = _request()
    aes = MagicMock()
    aes.decode.side_effect = lambda value: f"plain-{value}" if value != "bad" else (_ for _ in ()).throw(ValueError("bad cipher"))
    with patch("apps.node_mgmt.services.sidecar.AESCryptor", return_value=aes), patch.object(
        Sidecar,
        "get_cloud_region_secret_envconfig",
        return_value={NodeConstants.NATS_PASSWORD_KEY: "nats-secret", "DB_PASSWORD": "from-region"},
    ):
        resp = Sidecar.get_node_config_env(req, node.id, config.id)
    body = json.loads(resp.content)
    assert body["id"] == config.id
    env = body["env_config"]
    assert env["NATS_PASSWORD"] == "nats-secret"
    assert env["DB_PASSWORD"] == "plain-enc-child"
    assert env["PLAIN"] == "keep"
    assert env["EXTRA"] == "12"
    aes.decode.assert_called()

    config.env_config = {"NATS_PASSWORD": "bad"}
    config.save(update_fields=["env_config"])
    aes.decode.side_effect = ValueError("cannot decode")
    with patch("apps.node_mgmt.services.sidecar.AESCryptor", return_value=aes), patch.object(
        Sidecar, "get_cloud_region_secret_envconfig", return_value={}
    ):
        fallback = json.loads(Sidecar.get_node_config_env(req, node.id, config.id).content)
    assert fallback["env_config"]["NATS_PASSWORD"] == "bad"
