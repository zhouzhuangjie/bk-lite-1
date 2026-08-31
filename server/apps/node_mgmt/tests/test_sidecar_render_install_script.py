"""OpenSidecarViewSet.render_install_script：缺 token / 缺环境变量 / webhook 成功返回脚本。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.node_mgmt.constants.node import NodeConstants
from apps.node_mgmt.models.cloud_region import CloudRegion, SidecarEnv
from apps.node_mgmt.views.sidecar import OpenSidecarViewSet

pytestmark = pytest.mark.django_db


def test_render_install_script_requires_token():
    view = OpenSidecarViewSet()
    with pytest.raises(BaseAppException, match="Missing token parameter"):
        view.render_install_script(SimpleNamespace(query_params={}))


def test_render_install_script_requires_server_and_webhook_urls():
    region = CloudRegion.objects.create(name="render-region")
    token_data = {
        "node_id": "n1",
        "ip": "10.0.0.1",
        "user": "root",
        "os": "linux",
        "package_id": 9,
        "cloud_region_id": region.id,
        "organizations": [1, 2],
        "node_name": "node-1",
        "remaining_usage": 4,
    }
    view = OpenSidecarViewSet()
    req = SimpleNamespace(query_params={"token": "tok"})
    with patch(
        "apps.node_mgmt.views.sidecar.InstallTokenService.validate_and_get_token_data",
        return_value=token_data,
    ), patch("apps.node_mgmt.views.sidecar.generate_node_token", return_value="sidecar-tok"), patch(
        "apps.node_mgmt.views.sidecar.InstallTokenService.generate_download_token",
        return_value="dl-tok",
    ):
        with pytest.raises(BaseAppException, match="Missing NODE_SERVER_URL"):
            view.render_install_script(req)

        SidecarEnv.objects.create(key=NodeConstants.SERVER_URL_KEY, value="http://server", cloud_region=region)
        with pytest.raises(BaseAppException, match="Missing WEBHOOK_SERVER_URL"):
            view.render_install_script(req)


def test_render_install_script_returns_plain_text_from_webhook():
    region = CloudRegion.objects.create(name="render-ok")
    SidecarEnv.objects.create(key=NodeConstants.SERVER_URL_KEY, value="http://server/", cloud_region=region)
    SidecarEnv.objects.create(key="WEBHOOK_SERVER_URL", value="http://hook/", cloud_region=region)
    token_data = {
        "node_id": "n2",
        "ip": "10.0.0.2",
        "user": "root",
        "os": "linux",
        "package_id": 3,
        "cloud_region_id": region.id,
        "organizations": [8],
        "node_name": "node-2",
        "remaining_usage": 2,
    }
    webhook = MagicMock()
    webhook.status_code = 200
    webhook.json.return_value = {"install_script": "echo install"}
    view = OpenSidecarViewSet()
    req = SimpleNamespace(query_params={"token": "tok"})
    with patch(
        "apps.node_mgmt.views.sidecar.InstallTokenService.validate_and_get_token_data",
        return_value=token_data,
    ), patch("apps.node_mgmt.views.sidecar.generate_node_token", return_value="sidecar-tok"), patch(
        "apps.node_mgmt.views.sidecar.InstallTokenService.generate_download_token",
        return_value="dl-tok",
    ), patch("apps.node_mgmt.views.sidecar.requests.post", return_value=webhook) as post, patch(
        "apps.node_mgmt.views.sidecar.get_webhook_tls_verify",
        return_value=False,
    ):
        resp = view.render_install_script(req)
    assert resp.status_code == 200
    assert resp.content.decode("utf-8") == "echo install"
    assert resp["Content-Type"].startswith("text/plain")
    assert resp["X-Token-Remaining-Usage"] == "2"
    body = post.call_args.kwargs["json"]
    assert body["node_id"] == "n2"
    assert body["api_token"] == "sidecar-tok"
    assert body["group_id"] == "8"
    assert "token=dl-tok" in body["file_url"]
    assert post.call_args.args[0] == "http://hook/infra/sidecar"
