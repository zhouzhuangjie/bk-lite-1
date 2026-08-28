"""NATS 节点服务：按 CPU 架构解析采集器，ARM 不回落到 x86。"""
import pytest
from apps.node_mgmt.models import CloudRegion, Collector, Node

from apps.node_mgmt.constants.node import NodeConstants
from apps.node_mgmt.models import CloudRegion, Collector, Node
from apps.node_mgmt.nats.node import NatsService

pytestmark = pytest.mark.django_db


def test_allowed_architectures_arm_does_not_include_x86():
    assert NatsService._allowed_architectures(NodeConstants.ARM64_ARCH) == [NodeConstants.ARM64_ARCH]
    assert NodeConstants.X86_64_ARCH in NatsService._allowed_architectures(NodeConstants.X86_64_ARCH)
    assert "" in NatsService._allowed_architectures("unknown")


def test_resolve_collector_for_node_prefers_matching_arch():
    region = CloudRegion.objects.create(name="nats-arch-region")
    x86 = Collector.objects.create(
        id="telegraf-x86-nats",
        name="Telegraf",
        service_type="exec",
        node_operating_system=NodeConstants.LINUX_OS,
        cpu_architecture=NodeConstants.X86_64_ARCH,
        executable_path="/opt/telegraf",
        execute_parameters="--config %s",
    )
    arm = Collector.objects.create(
        id="telegraf-arm-nats",
        name="Telegraf",
        service_type="exec",
        node_operating_system=NodeConstants.LINUX_OS,
        cpu_architecture=NodeConstants.ARM64_ARCH,
        executable_path="/opt/telegraf",
        execute_parameters="--config %s",
    )
    arm_node = Node.objects.create(
        id="arm-node-1",
        name="arm-node-1",
        ip="10.0.0.8",
        operating_system=NodeConstants.LINUX_OS,
        cpu_architecture="aarch64",
        collector_configuration_directory="/etc/collector",
        cloud_region=region,
    )
    x86_node = Node.objects.create(
        id="x86-node-1",
        name="x86-node-1",
        ip="10.0.0.9",
        operating_system=NodeConstants.LINUX_OS,
        cpu_architecture="amd64",
        collector_configuration_directory="/etc/collector",
        cloud_region=region,
    )
    assert NatsService._resolve_collector_for_node(arm_node, "Telegraf").id == arm.id
    assert NatsService._resolve_collector_for_node(x86_node, "Telegraf").id == x86.id
    missing = Node.objects.create(
        id="win-node-1",
        name="win-node-1",
        ip="10.0.0.10",
        operating_system=NodeConstants.WINDOWS_OS,
        cpu_architecture=NodeConstants.X86_64_ARCH,
        collector_configuration_directory="/etc/collector",
        cloud_region=region,
    )
    assert NatsService._resolve_collector_for_node(missing, "Telegraf") is None
