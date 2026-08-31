"""Sidecar 环境变量序列化：secret 掩码与加解密。"""
import uuid
from unittest.mock import patch

import pytest

from apps.node_mgmt.constants.database import EnvVariableConstants
from apps.node_mgmt.models.cloud_region import CloudRegion, SidecarEnv
from apps.node_mgmt.serializers.sidecar_env import (
    EnvVariableCreateSerializer,
    SidecarEnvSerializer,
)

pytestmark = pytest.mark.django_db


def test_sidecar_env_masks_secret_and_encrypts_on_create():
    region = CloudRegion.objects.create(name=f"r-env-{uuid.uuid4().hex[:8]}", introduction="")
    env = SidecarEnv.objects.create(
        cloud_region=region,
        key="TOKEN",
        value="plain",
        type=EnvVariableConstants.TYPE_SECRET,
        description="d",
    )
    data = SidecarEnvSerializer(env).data
    assert data["value"] == EnvVariableConstants.SECRET_MASK
    assert data["key"] == "TOKEN"

    with patch("apps.node_mgmt.serializers.sidecar_env.AESCryptor") as aes:
        aes.return_value.encode.return_value = "enc-token"
        created = SidecarEnvSerializer().create(
            {"cloud_region": region, "key": "K", "value": "secret", "type": EnvVariableConstants.TYPE_SECRET, "description": ""}
        )
    assert created.value == "enc-token"
    aes.return_value.encode.assert_called_once_with("secret")

    plain = SidecarEnvSerializer().create(
        {"cloud_region": region, "key": "P", "value": "v", "type": "normal", "description": ""}
    )
    assert plain.value == "v"

    with patch("apps.node_mgmt.serializers.sidecar_env.AESCryptor") as aes:
        aes.return_value.encode.return_value = "enc2"
        ser = EnvVariableCreateSerializer()
        obj = ser.create(
            {"cloud_region": region, "key": "C", "value": "s", "type": EnvVariableConstants.TYPE_SECRET, "description": ""}
        )
    assert obj.value == "enc2"

    with patch("apps.node_mgmt.serializers.sidecar_env.AESCryptor") as aes:
        aes.return_value.encode.return_value = "enc-upd"
        updated = SidecarEnvSerializer().update(plain, {"value": "new-secret", "type": EnvVariableConstants.TYPE_SECRET})
    assert updated.value == "enc-upd"
