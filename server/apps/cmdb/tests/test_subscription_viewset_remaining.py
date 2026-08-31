"""SubscriptionViewSet：空组织/非法 team 返回空集、无管理权 403、toggle 翻转。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.cmdb.models.subscription_rule import SubscriptionRule
from apps.cmdb.views.subscription import SubscriptionViewSet

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()
VIEWS = "apps.cmdb.views.subscription"


def _actor():
    user = UserFactory(domain="domain.com", is_superuser=True)
    user.username = "sub-admin"
    user.domain = "domain.com"
    return user


def _rule(**kwargs):
    defaults = dict(
        name=kwargs.pop("name", f"rule-{SubscriptionRule.objects.count()}"),
        organization=1,
        model_id="host",
        filter_type="instances",
        instance_filter={"instance_ids": [1]},
        trigger_types=["create"],
        recipients={"user_ids": ["u1"]},
        channel_ids=[1],
        is_enabled=True,
    )
    defaults.update(kwargs)
    return SubscriptionRule.objects.create(**defaults)


def _req(method, actor, data=None, team="1"):
    fn = getattr(factory, method)
    request = fn("/api/subscription/", data=data or {}, format="json") if data is not None else fn("/api/subscription/")
    request.COOKIES["current_team"] = team
    force_authenticate(request, user=actor)
    return request


def _body(resp):
    if hasattr(resp, "render"):
        resp.render()
        return json.loads(resp.rendered_content)
    return json.loads(resp.content)


def test_get_queryset_rejects_empty_and_invalid_team(monkeypatch):
    _rule(organization=1)
    vs = SubscriptionViewSet()
    monkeypatch.setattr(f"{VIEWS}.get_current_team", lambda request: None)
    vs.request = SimpleNamespace()
    assert list(vs.get_queryset()) == []
    monkeypatch.setattr(f"{VIEWS}.get_current_team", lambda request: "abc")
    assert list(vs.get_queryset()) == []
    monkeypatch.setattr(f"{VIEWS}.get_current_team", lambda request: "1")
    monkeypatch.setattr(f"{VIEWS}.GroupUtils.get_group_with_descendants", staticmethod(lambda gid: [1, 2]))
    other = _rule(name="other-org", organization=9)
    ids = set(vs.get_queryset().values_list("organization", flat=True))
    assert 1 in ids
    assert 9 not in ids
    assert other.organization == 9


def test_update_destroy_toggle_require_manage_permission():
    actor = _actor()
    rule = _rule(name="locked")
    with patch.object(SubscriptionViewSet, "_check_manage_permission", return_value=False):
        resp = SubscriptionViewSet.as_view({"put": "update"})(
            _req("put", actor, {"name": "x", "organization": 1, "model_id": "host"}),
            pk=rule.id,
        )
    assert resp.status_code == 403
    assert _body(resp)["message"] == "仅所属组织可管理"

    with patch.object(SubscriptionViewSet, "_check_manage_permission", return_value=False):
        resp = SubscriptionViewSet.as_view({"delete": "destroy"})(_req("delete", actor), pk=rule.id)
    assert resp.status_code == 403
    assert SubscriptionRule.objects.filter(id=rule.id).exists()

    with patch.object(SubscriptionViewSet, "_check_manage_permission", return_value=False):
        resp = SubscriptionViewSet.as_view({"post": "toggle"})(_req("post", actor), pk=rule.id)
    assert resp.status_code == 403
    rule.refresh_from_db()
    assert rule.is_enabled is True


def test_toggle_flips_enabled_when_manage_allowed():
    actor = _actor()
    rule = _rule(name="flip", is_enabled=True)
    with patch.object(SubscriptionViewSet, "_check_manage_permission", return_value=True):
        resp = SubscriptionViewSet.as_view({"post": "toggle"})(_req("post", actor), pk=rule.id)
    assert resp.status_code == 200
    rule.refresh_from_db()
    assert rule.is_enabled is False
    assert rule.updated_by == actor.username
    assert _body(resp)["data"]["is_enabled"] is False


def test_retrieve_create_and_destroy_success_paths():
    actor = _actor()
    rule = _rule(name="shown")
    with patch(f"{VIEWS}.GroupUtils.get_group_with_descendants", staticmethod(lambda gid: [1])):
        resp = SubscriptionViewSet.as_view({"get": "retrieve"})(_req("get", actor), pk=rule.id)
    assert resp.status_code == 200
    assert _body(resp)["data"]["name"] == "shown"

    payload = {
        "name": "created-rule",
        "organization": 1,
        "model_id": "host",
        "filter_type": "instances",
        "instance_filter": {"instance_ids": [1]},
        "trigger_types": ["attribute_change"],
        "trigger_config": {"attribute_change": {"fields": ["name"]}},
        "recipients": {"users": ["u1"], "groups": []},
        "channel_ids": [1],
        "is_enabled": True,
    }
    resp = SubscriptionViewSet.as_view({"post": "create"})(_req("post", actor, payload))
    assert resp.status_code == 200
    created = _body(resp)["data"]
    assert created["name"] == "created-rule"
    assert created["created_by"] == actor.username
    assert SubscriptionRule.objects.filter(id=created["id"]).exists()

    with patch.object(SubscriptionViewSet, "_check_manage_permission", return_value=True):
        resp = SubscriptionViewSet.as_view({"delete": "destroy"})(_req("delete", actor), pk=created["id"])
    assert resp.status_code == 200
    assert not SubscriptionRule.objects.filter(id=created["id"]).exists()


def test_check_manage_permission_delegates_to_subscription_utils(monkeypatch):
    captured = {}

    def _check(org, team):
        captured["org"] = org
        captured["team"] = team
        return True

    monkeypatch.setattr(f"{VIEWS}.check_subscription_manage_permission", _check)
    monkeypatch.setattr(f"{VIEWS}.get_current_team", lambda request: 7)
    rule = SimpleNamespace(organization=3)
    assert SubscriptionViewSet._check_manage_permission(rule, SimpleNamespace()) is True
    assert captured == {"org": 3, "team": 7}
