"""NodeMgmtView 剩余 action：插件节点选择器、批量配置、实例配置查询与更新。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.core.exceptions.base_app_exception import BaseAppException
from apps.monitor.views.node_mgmt import NodeMgmtView, _build_actor_context

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()
VIEWS = "apps.monitor.views.node_mgmt"


def _actor(superuser=True):
    user = UserFactory(
        is_superuser=superuser,
        domain="domain.com",
        group_list=[{"id": 1, "name": "OpsPilotGuest"}, {"id": 2, "name": "T2"}],
    )
    return user


def _req(user, data):
    request = factory.post("/api/node_mgmt/", data=data, format="json")
    request.COOKIES["current_team"] = "1"
    force_authenticate(request, user=user)
    return request


def test_build_actor_context_rejects_missing_and_non_int_team():
    user = SimpleNamespace(username="u", domain="d", is_superuser=True, group_list=[])
    with pytest.raises(BaseAppException, match="缺少 current_team 参数"):
        _build_actor_context(SimpleNamespace(user=user, COOKIES={}))
    with pytest.raises(BaseAppException, match="current_team 参数非法"):
        _build_actor_context(SimpleNamespace(user=user, COOKIES={"current_team": "x"}))
    ctx = _build_actor_context(
        SimpleNamespace(user=user, COOKIES={"current_team": "4", "include_children": "1"})
    )
    assert ctx["current_team"] == 4
    assert ctx["include_children"] is True


def test_get_nodes_merges_plugin_selector_and_guest_org():
    user = _actor(superuser=False)
    with (
        patch(f"{VIEWS}.InstanceConfigService._get_plugin_node_selector", return_value={"os": "linux"}),
        patch(f"{VIEWS}.merge_node_query_with_selector", side_effect=lambda q, sel: {**q, **sel}) as merge,
        patch(f"{VIEWS}.NodeMgmt") as rpc,
    ):
        rpc.return_value.node_list.return_value = {"count": 1, "nodes": [{"id": "n1"}]}
        resp = NodeMgmtView.as_view({"post": "get_nodes"})(
            _req(user, {"monitor_plugin_id": 9, "page": 1, "page_size": 5, "os": "linux"})
        )
    assert resp.status_code == 200
    query = rpc.return_value.node_list.call_args.args[0]
    assert 1 in query["organization_ids"]
    assert query["os"] == "linux"
    merge.assert_called_once()


def test_batch_setting_and_instance_config_actions_delegate():
    user = _actor()
    with patch(f"{VIEWS}.InstanceConfigService.create_monitor_instance_by_node_mgmt") as create:
        resp = NodeMgmtView.as_view({"post": "batch_setting_node_child_config"})(_req(user, {"nodes": [1]}))
    assert resp.status_code == 200
    create.assert_called_once()

    with patch(f"{VIEWS}.InstanceConfigService.get_instance_configs", return_value=[{"id": "c1"}]) as getter:
        resp = NodeMgmtView.as_view({"post": "get_instance_child_config"})(
            _req(user, {"instance_id": "h1", "collector": "telegraf", "collect_type": "host"})
        )
    assert json.loads(resp.content)["data"] == [{"id": "c1"}]
    assert getter.call_args.args[0] == "h1"

    with patch(f"{VIEWS}.InstanceConfigService.update_instance_config") as update:
        resp = NodeMgmtView.as_view({"post": "update_instance_collect_config"})(
            _req(user, {"child": {"a": 1}, "base": {"b": 2}})
        )
    assert resp.status_code == 200
    update.assert_called_once()
    assert update.call_args.args[0] == {"a": 1}
    assert update.call_args.args[1] == {"b": 2}
