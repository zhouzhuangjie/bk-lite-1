"""监控：实例状态、分页、Infra 渲染、分组任务与初始化命令。"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.core.management import call_command

from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.models.monitor_object import MonitorInstance, MonitorObject
from apps.monitor.serializers.monitor_instance import MonitorInstanceSerializer
from apps.monitor.services.infra import InfraService
from apps.monitor.utils.instance import calculation_status
from apps.monitor.utils.pagination import parse_page_params
from apps.monitor.views.infra import InfraViewSet
from apps.monitor.views.system_mgmt import SystemMgmtView, _build_actor_context

pytestmark = pytest.mark.django_db


def test_calculation_status_buckets_by_age():
    now = int(datetime.now(timezone.utc).timestamp())
    assert calculation_status(0) == ""
    assert calculation_status(None) == ""
    assert calculation_status(now - 10) == "normal"
    assert calculation_status(now - 600) == "inactive"
    assert calculation_status(now - 4000) == "unavailable"


def test_parse_page_params_falls_back_and_allows_all():
    assert parse_page_params({}) == (1, 10)
    assert parse_page_params({"page": "x", "page_size": "y"}) == (1, 10)
    assert parse_page_params({"page": 0, "page_size": 0}) == (1, 10)
    assert parse_page_params({"page": 2, "page_size": -1}, allow_page_size_all=True) == (2, -1)
    assert parse_page_params({"page": "3", "page_size": "20"}) == (3, 20)


def test_instance_serializer_roundtrip():
    obj = MonitorObject.objects.create(name="Host-status-init", level="base")
    inst = MonitorInstance.objects.create(id="h-status-init-1", name="h1", monitor_object=obj)
    data = MonitorInstanceSerializer(inst).data
    assert data["id"] == inst.id
    assert data["name"] == "h1"
    assert data["monitor_object"] == obj.id


def test_infra_view_requires_token_and_sets_remaining_header():
    vs = InfraViewSet()
    with pytest.raises(BaseAppException, match="Missing required parameter: token"):
        vs.render(SimpleNamespace(data={}))
    with (
        patch(
            "apps.monitor.views.infra.InfraService.validate_and_get_token_data",
            return_value={"cluster_name": "c1", "cloud_region_id": 2, "remaining_usage": 4},
        ),
        patch(
            "apps.monitor.views.infra.InfraService.render_config_from_cloud_region",
            return_value="kind: DaemonSet\n",
        ) as render,
    ):
        resp = vs.render(SimpleNamespace(data={"token": "abc"}))
    render.assert_called_once_with(cluster_name="c1", cloud_region_id=2, config_type="metric")
    assert resp.content == b"kind: DaemonSet\n"
    assert resp["X-Token-Remaining-Usage"] == "4"
    assert "yaml" in resp["Content-Type"]


def test_infra_render_from_cloud_region_requires_env_and_posts_yaml():
    env = {
        "NATS_USERNAME": "u",
        "NATS_PASSWORD": "p",
        "NATS_SERVERS": "nats://n:4222",
        "NATS_TLS_CA": "ca",
        "WEBHOOK_SERVER_URL": "https://wh",
    }
    with patch("apps.monitor.services.infra.NodeMgmt") as rpc:
        rpc.return_value.get_cloud_region_envconfig.return_value = {"NATS_USERNAME": "u"}
        with pytest.raises(BaseAppException, match="Missing required environment variables"):
            InfraService.render_config_from_cloud_region("c1", "9")

    resp = MagicMock(status_code=200)
    resp.json.return_value = {"yaml": "kind: Pod"}
    with (
        patch("apps.monitor.services.infra.NodeMgmt") as rpc,
        patch("apps.monitor.services.infra.requests.post", return_value=resp) as post,
        patch("apps.monitor.services.infra.get_webhook_tls_verify", return_value=True),
    ):
        rpc.return_value.get_cloud_region_envconfig.return_value = env
        yaml = InfraService.render_config_from_cloud_region("c1", "9", config_type="metric")
    assert yaml == "kind: Pod"
    post.assert_called_once()
    assert post.call_args.args[0] == "https://wh/infra/kubernetes"
    assert post.call_args.kwargs["json"]["cluster_name"] == "c1"


def test_infra_render_from_api_error_paths(monkeypatch):
    with pytest.raises(BaseAppException, match="Webhook API URL is required"):
        InfraService.render_config_from_api({}, None)

    bad = MagicMock(status_code=500, text="oops")
    monkeypatch.setattr("apps.monitor.services.infra.requests.post", lambda *a, **k: bad)
    with pytest.raises(BaseAppException, match="Infra API returned status 500"):
        InfraService.render_config_from_api({"a": 1}, "https://wh")

    empty = MagicMock(status_code=200)
    empty.json.return_value = {}
    monkeypatch.setattr("apps.monitor.services.infra.requests.post", lambda *a, **k: empty)
    with pytest.raises(BaseAppException, match="missing 'yaml' field"):
        InfraService.render_config_from_api({"a": 1}, "https://wh")

    def timeout(*a, **k):
        raise requests.Timeout("slow")

    monkeypatch.setattr("apps.monitor.services.infra.requests.post", timeout)
    with pytest.raises(BaseAppException, match="Infra API request timeout"):
        InfraService.render_config_from_api({"a": 1}, "https://wh")

    def conn(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("apps.monitor.services.infra.requests.post", conn)
    with pytest.raises(BaseAppException, match="Infra API request failed"):
        InfraService.render_config_from_api({"a": 1}, "https://wh")

    boom = MagicMock(status_code=200)
    boom.json.side_effect = ValueError("bad json")
    monkeypatch.setattr("apps.monitor.services.infra.requests.post", lambda *a, **k: boom)
    with pytest.raises(BaseAppException, match="Failed to parse response"):
        InfraService.render_config_from_api({"a": 1}, "https://wh")


def test_grouping_rule_task_and_init_commands(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "apps.monitor.tasks.grouping_rule.SyncInstance",
        lambda: SimpleNamespace(run=lambda: calls.append("sync")),
    )
    monkeypatch.setattr(
        "apps.monitor.tasks.grouping_rule.RuleGrouping",
        lambda: SimpleNamespace(update_grouping=lambda: calls.append("group")),
    )
    from apps.monitor.tasks.grouping_rule import sync_instance_and_group

    sync_instance_and_group()
    assert calls == ["sync", "group"]

    monkeypatch.setattr("apps.monitor.management.commands.plugin_init.migrate_plugin", lambda: calls.append("plugin"))
    monkeypatch.setattr("apps.monitor.management.commands.plugin_init.migrate_policy", lambda: calls.append("policy"))
    monkeypatch.setattr(
        "apps.monitor.management.commands.plugin_init.migrate_default_order",
        lambda: calls.append("order"),
    )
    call_command("plugin_init")
    assert calls[-3:] == ["plugin", "policy", "order"]

    monkeypatch.setattr(
        "apps.monitor.management.commands.autodiscover.sync_instance_and_group",
        lambda: calls.append("autodiscover"),
    )
    call_command("autodiscover")
    assert calls[-1] == "autodiscover"


def test_system_mgmt_actor_context_and_channel_list(monkeypatch):
    user = SimpleNamespace(username="alice", domain="d.com", is_superuser=True, group_list=[{"id": 3}])
    with pytest.raises(BaseAppException, match="缺少 current_team 参数"):
        _build_actor_context(SimpleNamespace(user=user, COOKIES={}))
    with pytest.raises(BaseAppException, match="current_team 参数非法"):
        _build_actor_context(SimpleNamespace(user=user, COOKIES={"current_team": "x"}))
    ctx = _build_actor_context(
        SimpleNamespace(user=user, COOKIES={"current_team": "8", "include_children": "1"})
    )
    assert ctx["current_team"] == 8
    assert ctx["include_children"] is True
    assert ctx["username"] == "alice"
    assert ctx["group_list"] == [3]

    captured = {}
    monkeypatch.setattr(
        "apps.monitor.views.system_mgmt.SystemMgmtUtils.search_channel_list",
        staticmethod(lambda actor, teams, include_children: captured.update(teams=teams, include_children=include_children) or [{"id": 1}]),
    )
    req = SimpleNamespace(user=user, COOKIES={"current_team": "8", "include_children": "0"})
    resp = SystemMgmtView().search_channel_list(req)
    body = json.loads(resp.content.decode("utf-8"))
    assert body["data"] == [{"id": 1}]
    assert captured["teams"] == [8]
    assert captured["include_children"] is False
