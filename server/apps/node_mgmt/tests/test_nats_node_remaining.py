"""节点 NATS 剩余：架构选择、父配置守卫与云区域代理地址。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.node_mgmt.constants.database import EnvVariableConstants
from apps.node_mgmt.constants.node import NodeConstants
from apps.node_mgmt.models import CloudRegion, Node, NodeOrganization, SidecarEnv
from apps.node_mgmt.nats.node import NatsService, get_cloud_region_proxy_address

pytestmark = pytest.mark.django_db


def test_allowed_architectures_and_resolve_collector_for_node():
    assert NatsService._allowed_architectures("aarch64") == [NodeConstants.ARM64_ARCH]
    assert NatsService._allowed_architectures("amd64") == [NodeConstants.X86_64_ARCH, ""]
    assert NatsService._allowed_architectures("ppc64") == ["", NodeConstants.X86_64_ARCH]

    node = SimpleNamespace(operating_system=NodeConstants.LINUX_OS, cpu_architecture="arm64")
    with patch.object(NatsService, "_allowed_architectures", return_value=[NodeConstants.ARM64_ARCH]):
        qs = MagicMock()
        qs.filter.return_value.order_by.return_value = []
        with patch("apps.node_mgmt.nats.node.Collector.objects", qs):
            assert NatsService._resolve_collector_for_node(node, "Telegraf") is None

        arm = SimpleNamespace(cpu_architecture="arm64")
        x86 = SimpleNamespace(cpu_architecture="x86_64")
        qs.filter.return_value.order_by.return_value = [arm]
        with patch("apps.node_mgmt.nats.node.Collector.objects", qs):
            assert NatsService._resolve_collector_for_node(node, "Telegraf") is arm

        node.cpu_architecture = "x86_64"
        qs.filter.return_value.order_by.return_value = [x86, SimpleNamespace(cpu_architecture="")]
        with patch("apps.node_mgmt.nats.node.Collector.objects", qs):
            assert NatsService._resolve_collector_for_node(node, "Telegraf") is x86


def test_ensure_parent_configs_raises_for_missing_node_collector_and_flags():
    svc = NatsService()
    svc._ensure_parent_configs_for_child_configs([])
    configs = [{"node_id": "n1", "collector_name": "Telegraf"}]
    existing_qs = MagicMock()
    existing_qs.filter.return_value.values_list.return_value.distinct.return_value = set()
    node_qs = MagicMock()
    node_qs.filter.return_value.select_related.return_value = []
    with (
        patch("apps.node_mgmt.nats.node.CollectorConfiguration.objects", existing_qs),
        patch("apps.node_mgmt.nats.node.Node.objects", node_qs),
    ):
        with pytest.raises(BaseAppException, match="节点 n1 不存在"):
            svc._ensure_parent_configs_for_child_configs(configs)

    node = SimpleNamespace(id="n1", operating_system="linux", cpu_architecture="x86_64")
    node_qs.filter.return_value.select_related.return_value = [node]
    with (
        patch("apps.node_mgmt.nats.node.CollectorConfiguration.objects", existing_qs),
        patch("apps.node_mgmt.nats.node.Node.objects", node_qs),
        patch.object(NatsService, "_resolve_collector_for_node", return_value=None),
    ):
        with pytest.raises(BaseAppException, match="采集器 Telegraf 不存在"):
            svc._ensure_parent_configs_for_child_configs(configs)

    collector = SimpleNamespace(controller_default_run=False, default_config={"x": 1})
    with (
        patch("apps.node_mgmt.nats.node.CollectorConfiguration.objects", existing_qs),
        patch("apps.node_mgmt.nats.node.Node.objects", node_qs),
        patch.object(NatsService, "_resolve_collector_for_node", return_value=collector),
    ):
        with pytest.raises(BaseAppException, match="未启用默认父配置创建"):
            svc._ensure_parent_configs_for_child_configs(configs)

    collector = SimpleNamespace(controller_default_run=True, default_config={})
    with (
        patch("apps.node_mgmt.nats.node.CollectorConfiguration.objects", existing_qs),
        patch("apps.node_mgmt.nats.node.Node.objects", node_qs),
        patch.object(NatsService, "_resolve_collector_for_node", return_value=collector),
    ):
        with pytest.raises(BaseAppException, match="缺少 default_config"):
            svc._ensure_parent_configs_for_child_configs(configs)


def test_cloud_region_proxy_address_org_gate_and_secret_decode():
    region = CloudRegion.objects.create(name="proxy-region-90", introduction="", created_by="t", updated_by="t")
    assert get_cloud_region_proxy_address(str(region.id), organization_ids=[99]) == ""

    node = Node.objects.create(
        id="proxy-node-90",
        name="proxy-node-90",
        ip="10.9.0.1",
        operating_system=NodeConstants.LINUX_OS,
        collector_configuration_directory="/etc/collector",
        cloud_region=region,
        created_by="t",
        updated_by="t",
    )
    NodeOrganization.objects.create(node=node, organization=7, created_by="t", updated_by="t")
    region.proxy_address = "http://proxy.local:8080"
    region.save(update_fields=["proxy_address"])
    assert get_cloud_region_proxy_address(str(region.id), organization_ids=[7]) == "http://proxy.local:8080"

    region.proxy_address = ""
    region.save(update_fields=["proxy_address"])
    SidecarEnv.objects.create(
        cloud_region=region,
        key=EnvVariableConstants.PROXY_ADDRESS_KEY,
        value="cipher",
        type=EnvVariableConstants.TYPE_SECRET,
    )
    with patch("apps.node_mgmt.nats.node.AESCryptor") as aes:
        aes.return_value.decode.return_value = "http://decoded"
        assert get_cloud_region_proxy_address(str(region.id)) == "http://decoded"
        aes.return_value.decode.side_effect = ValueError("bad")
        assert get_cloud_region_proxy_address(str(region.id)) == "cipher"
