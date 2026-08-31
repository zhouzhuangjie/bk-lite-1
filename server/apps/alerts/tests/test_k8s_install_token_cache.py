"""K8s 安装 token：缓存写入、过期与用量上限。"""
from unittest.mock import patch

import pytest

from apps.alerts.service.k8s_install import K8sInstallService
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.unit


def test_generate_and_consume_install_token():
    store = {}

    class _Cache:
        def set(self, key, value, timeout=None):
            store[key] = dict(value)

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

    payload = {
        "server_url": "https://host",
        "cluster_name": "prod",
        "push_source_id": "k8s",
        "source_id": "src",
        "receiver_url": "https://host/recv",
        "secret": "sec",
    }
    with patch("apps.alerts.service.k8s_install.cache", _Cache()):
        token = K8sInstallService.generate_install_token(payload)
        data = K8sInstallService.validate_and_get_token_data(token)
        assert data["remaining_usage"] == K8sInstallService.TOKEN_MAX_USAGE - 1
        assert data["cluster_name"] == "prod"

        key = K8sInstallService._build_cache_key(token)
        store[key]["usage_count"] = K8sInstallService.TOKEN_MAX_USAGE
        with pytest.raises(BaseAppException, match="Token has exceeded maximum usage limit"):
            K8sInstallService.validate_and_get_token_data(token)
        assert key not in store

        with pytest.raises(BaseAppException, match="Invalid or expired token"):
            K8sInstallService.validate_and_get_token_data("gone")
        with pytest.raises(BaseAppException, match="Token is required"):
            K8sInstallService.validate_and_get_token_data("")
        with pytest.raises(BaseAppException, match="推送来源不能为空"):
            K8sInstallService.normalize_push_source_id("  ")
        assert K8sInstallService.normalize_push_source_id(None) == "k8s"
