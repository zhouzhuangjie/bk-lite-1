"""云区域初始化与 node token 初始化命令契约。"""
from unittest.mock import patch
from uuid import UUID

import pytest
from django.core.management import call_command

from apps.node_mgmt.constants.cloudregion_service import CloudRegionServiceConstants
from apps.node_mgmt.constants.database import CloudRegionConstants, EnvVariableConstants
from apps.node_mgmt.management.services.node_init.cloud_init import cloud_init
from apps.node_mgmt.models.cloud_region import CloudRegion, CloudRegionService, SidecarEnv

pytestmark = pytest.mark.django_db


class _FakeAES:
    def encode(self, value):
        return f"enc:{value}"


def test_cloud_init_creates_default_region_services_and_typed_env(monkeypatch):
    SidecarEnv.objects.filter(
        cloud_region_id=CloudRegionConstants.DEFAULT_CLOUD_REGION_ID,
        key__in=["FOO", "DB_PASSWORD", "NATS_TLS_CA"],
    ).delete()
    monkeypatch.setenv("DEFAULT_ZONE_VAR_FOO", "plain")
    monkeypatch.setenv("DEFAULT_ZONE_VAR_DB_PASSWORD", "secret")
    monkeypatch.setenv("DEFAULT_ZONE_VAR_NATS_TLS_CA", "cert")
    monkeypatch.setattr(
        "apps.node_mgmt.management.services.node_init.cloud_init.AESCryptor",
        _FakeAES,
    )
    cloud_init()
    region = CloudRegion.objects.get(id=CloudRegionConstants.DEFAULT_CLOUD_REGION_ID)
    assert region.name == CloudRegionConstants.DEFAULT_CLOUD_REGION_NAME
    assert region.introduction == CloudRegionConstants.DEFAULT_CLOUD_REGION_INTRODUCTION
    names = set(
        CloudRegionService.objects.filter(cloud_region=region).values_list("name", flat=True)
    )
    assert names >= set(CloudRegionServiceConstants.SERVICES)
    stargazer = CloudRegionService.objects.get(cloud_region=region, name="stargazer")
    assert stargazer.status == CloudRegionServiceConstants.NORMAL
    assert stargazer.deployed_status == CloudRegionServiceConstants.DEPLOYED
    assert SidecarEnv.objects.get(cloud_region=region, key="FOO").type == EnvVariableConstants.TYPE_NORMAL
    secret = SidecarEnv.objects.get(cloud_region=region, key="DB_PASSWORD")
    assert secret.type == EnvVariableConstants.TYPE_SECRET
    assert secret.value == "enc:secret"
    assert SidecarEnv.objects.get(cloud_region=region, key="NATS_TLS_CA").type == EnvVariableConstants.TYPE_TEXT


def test_cloud_init_swallows_exception(mocker):
    logger = mocker.patch("apps.node_mgmt.management.services.node_init.cloud_init.logger")
    with patch(
        "apps.node_mgmt.management.services.node_init.cloud_init.CloudRegion.objects.update_or_create",
        side_effect=RuntimeError("db down"),
    ):
        cloud_init()
    logger.exception.assert_called_once()


def test_node_token_init_prints_generated_token(mocker):
    mocker.patch(
        "apps.node_mgmt.management.commands.node_token_init.uuid.uuid1",
        return_value=UUID("12345678-1234-1234-1234-123456789abc"),
    )
    gen = mocker.patch(
        "apps.node_mgmt.management.commands.node_token_init.generate_node_token",
        return_value="tok-xyz",
    )
    logger = mocker.patch("apps.node_mgmt.management.commands.node_token_init.logger")
    call_command("node_token_init", "--ip", "10.0.0.8", "--user", "ops")
    gen.assert_called_once_with("12345678123412341234123456789abc", "10.0.0.8", "ops")
    messages = [call.args[0] for call in logger.info.call_args_list]
    assert messages == [
        "node token 初始化开始！",
        "node_id: 12345678123412341234123456789abc, token: tok-xyz",
        "node token 初始化完成！",
    ]
