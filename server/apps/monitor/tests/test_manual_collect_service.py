"""手动采集服务：字段校验、采集状态查询与安装命令。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.core.exceptions.base_app_exception import BaseAppException, ValidationAppException
from apps.monitor.models.monitor_object import MonitorObject
from apps.monitor.services.manual_collect import ManualCollectService

pytestmark = pytest.mark.django_db


def test_validate_and_build_manual_collect_payload():
    with pytest.raises(ValidationAppException, match="Use flow_asset for flow asset fields"):
        ManualCollectService._validate_create_fields({"ip": "1.1.1.1", "cloud_region_id": 2})
    ManualCollectService._validate_create_fields({"ip": "1.1.1.1"}, allow_flow_fields=True)
    payload, orgs = ManualCollectService._build_manual_collect_instance_data(
        {"id": "h1", "name": "host-1", "organizations": [3, 5]}
    )
    assert payload["auto"] is False
    assert payload["id"] == "('h1',)"
    assert orgs == [3, 5]
    assert "organizations" not in payload


def test_check_collect_status_object_query_and_result(monkeypatch):
    with pytest.raises(BaseAppException, match="监控对象不存在"):
        ManualCollectService.check_collect_status(999999, "('h1',)")

    obj = MonitorObject.objects.create(name="Host-mc-status", default_metric="up")
    with pytest.raises(BaseAppException, match="查询语句格式不正确"):
        ManualCollectService.check_collect_status(obj.id, "('h1',)")

    obj.default_metric = 'up{job="node"}'
    obj.save(update_fields=["default_metric"])
    monkeypatch.setattr(
        "apps.monitor.services.manual_collect.VictoriaMetricsAPI",
        lambda: SimpleNamespace(query=lambda q: {"data": {"result": [{"metric": {}}]}}),
    )
    assert ManualCollectService.check_collect_status(obj.id, "('h1',)") is True

    monkeypatch.setattr(
        "apps.monitor.services.manual_collect.VictoriaMetricsAPI",
        lambda: SimpleNamespace(query=lambda q: {"data": {"result": []}}),
    )
    assert ManualCollectService.check_collect_status(obj.id, "('h1',)") is False


def test_generate_install_command_requires_server_url_and_embeds_token():
    with patch("apps.rpc.node_mgmt.NodeMgmt") as rpc:
        rpc.return_value.get_cloud_region_envconfig.return_value = {}
        with pytest.raises(BaseAppException, match="Missing NODE_SERVER_URL"):
            ManualCollectService.generate_install_command("('cluster-a',)", "9")

    with (
        patch("apps.rpc.node_mgmt.NodeMgmt") as rpc,
        patch(
            "apps.monitor.services.manual_collect.InfraService.generate_install_token",
            return_value="tok-1",
        ) as token,
    ):
        rpc.return_value.get_cloud_region_envconfig.return_value = {"NODE_SERVER_URL": "https://node.example"}
        cmd = ManualCollectService.generate_install_command("('cluster-a',)", "9")
    token.assert_called_once_with("cluster-a", "9")
    assert "https://node.example/api/v1/monitor/open_api/infra/render/" in cmd
    assert '"token":"tok-1"' in cmd
    assert "kubectl apply -f -" in cmd
    assert ManualCollectService.get_install_config({}) == ""
