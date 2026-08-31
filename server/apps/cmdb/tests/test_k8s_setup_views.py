"""CMDB k8s 引导接入 ViewSet：缺参拒绝、token/command/verify 委托与 YAML 响应头。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.cmdb.views.k8s_setup import K8sSetupOpenViewSet, K8sSetupViewSet
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.unit


def _body(resp):
    return json.loads(resp.content.decode("utf-8"))


def test_install_token_and_command_require_cloud_region_id():
    vs = K8sSetupViewSet()
    with pytest.raises(BaseAppException, match="cloud_region_id is required"):
        vs.install_token(SimpleNamespace(data={}))
    with pytest.raises(BaseAppException, match="cloud_region_id is required"):
        vs.install_token(SimpleNamespace(data={"cloud_region_id": ""}))
    with pytest.raises(BaseAppException, match="cloud_region_id is required"):
        vs.install_command(SimpleNamespace(data={"collector_cluster_id": "c1"}))


def test_install_token_command_and_verify_delegate_to_service():
    vs = K8sSetupViewSet()
    with patch(
        "apps.cmdb.views.k8s_setup.K8sSetupService.generate_install_token",
        return_value={"token": "tok-1", "expire_seconds": 1800, "max_usage": 5},
    ) as gen:
        resp = vs.install_token(SimpleNamespace(data={"collector_cluster_id": "cls-1", "cloud_region_id": 9}))
    gen.assert_called_once_with("cls-1", 9)
    body = _body(resp)
    assert body["result"] is True
    assert body["data"] == {"token": "tok-1", "expire_seconds": 1800, "max_usage": 5}

    with patch(
        "apps.cmdb.views.k8s_setup.K8sSetupService.generate_install_command",
        return_value={"command": "curl | kubectl apply -f -", "token": "tok-2"},
    ) as cmd:
        resp = vs.install_command(SimpleNamespace(data={"collector_cluster_id": "cls-1", "cloud_region_id": 9}))
    cmd.assert_called_once_with("cls-1", 9)
    assert _body(resp)["data"]["command"] == "curl | kubectl apply -f -"

    with patch(
        "apps.cmdb.views.k8s_setup.K8sSetupService.verify_collector_reporting",
        return_value={"reported": True},
    ) as verify:
        resp = vs.verify(SimpleNamespace(data={"collector_cluster_id": "cls-1"}))
    verify.assert_called_once_with("cls-1")
    assert _body(resp)["data"] == {"reported": True}


def test_open_render_requires_token_and_sets_remaining_header():
    vs = K8sSetupOpenViewSet()
    with pytest.raises(BaseAppException, match="Missing required parameter: token"):
        vs.render(SimpleNamespace(data={}))

    with patch(
        "apps.cmdb.views.k8s_setup.K8sSetupService.render_yaml_by_token",
        return_value={"yaml": "kind: Namespace\n", "remaining_usage": 3},
    ) as render:
        resp = vs.render(SimpleNamespace(data={"token": "abc"}))
    render.assert_called_once_with("abc")
    assert resp.content == b"kind: Namespace\n"
    assert resp["X-Token-Remaining-Usage"] == "3"
    assert "yaml" in resp["Content-Type"]
