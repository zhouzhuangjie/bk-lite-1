"""NATS 剩余高风险鉴权：规则查询准备、子模块删规则、按应用取规则。"""
import pytest

from apps.system_mgmt import nats_api
from apps.system_mgmt.models import Group, GroupDataRule, Role, User, UserRule
from django.contrib.auth.hashers import make_password

pytestmark = pytest.mark.django_db


def _user(**kwargs):
    defaults = dict(
        username="nats-r13",
        display_name="NATS",
        email="nats-r13@example.com",
        password=make_password("secret"),
        domain="domain.com",
        group_list=[1],
        disabled=False,
    )
    defaults.update(kwargs)
    return User.objects.create(**defaults)


def test_prepare_user_rules_query_missing_admin_and_guest():
    assert nats_api._prepare_user_rules_query(1, "ghost", "domain.com", "opspilot") == (None, None, None, None, None)

    group = Group.objects.create(name="nats-r13-g")
    guest, _ = Group.objects.get_or_create(name="OpsPilotGuest", parent_id=0)
    admin_role, _ = Role.objects.get_or_create(name="admin", app="")
    admin = _user(username="nats-r13-admin", role_list=[admin_role.id], group_list=[group.id, guest.id])
    user_obj, query_ids, admin_teams, has_guest, is_admin = nats_api._prepare_user_rules_query(
        group.id, admin.username, "domain.com", "opspilot"
    )
    assert user_obj.id == admin.id
    assert is_admin is True
    assert has_guest is True
    assert group.id in query_ids
    assert guest.id in admin_teams


def test_prepare_user_rules_query_include_children(monkeypatch):
    group = Group.objects.create(name="nats-r13-parent")
    user = _user(username="nats-r13-child", group_list=[group.id], role_list=[])
    monkeypatch.setattr(
        "apps.system_mgmt.nats_api.GroupUtils.get_group_with_descendants_filtered",
        lambda gid, group_list=None: [gid, 88],
    )
    user_obj, query_ids, *_ = nats_api._prepare_user_rules_query(
        group.id, user.username, "domain.com", "opspilot", include_children=True
    )
    assert user_obj.id == user.id
    assert set(query_ids) == {group.id, 88}


def test_get_user_rules_by_app_child_module_and_missing_user():
    assert nats_api.get_user_rules_by_app(1, "ghost", "domain.com", "opspilot", "provider", "llm_model") == {
        "instance": [],
        "team": [],
    }
    group = Group.objects.create(name="nats-r13-app")
    user = _user(username="nats-r13-mod", group_list=[group.id], role_list=[])
    gdr = GroupDataRule.objects.create(
        name="provider-rule",
        app="opspilot",
        group_id=group.id,
        group_name=group.name,
        rules={"provider": {"llm_model": [{"id": 5, "permission": ["View"]}]}},
    )
    UserRule.objects.create(username=user.username, domain="domain.com", group_rule=gdr)
    scoped = nats_api.get_user_rules_by_app(
        group.id, user.username, "domain.com", "opspilot", "provider", "llm_model"
    )
    assert [item["id"] for item in scoped["instance"]] == [5]


def test_delete_rules_child_module_and_exception(monkeypatch):
    group = Group.objects.create(name="nats-r13-del")
    rule = GroupDataRule.objects.create(
        name="nested-rule",
        app="opspilot",
        group_id=group.id,
        group_name=group.name,
        rules={"provider": {"llm_model": [{"id": 11}, {"id": 22}]}},
    )
    result = nats_api.delete_rules([group.id], 11, "opspilot", "provider", "llm_model")
    assert result["result"] is True
    assert "1 group data rules" in result["message"]
    rule.refresh_from_db()
    assert [item["id"] for item in rule.rules["provider"]["llm_model"]] == [22]

    monkeypatch.setattr(
        "apps.system_mgmt.nats_api.GroupDataRule.objects.filter",
        lambda **k: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    failed = nats_api.delete_rules([group.id], 11, "opspilot", "provider", "llm_model")
    assert failed == {"result": False, "message": "db down"}


def test_get_group_id_missing_and_found():
    missing = nats_api.get_group_id("no-such-root")
    assert missing == {"result": False, "message": "group named 'no-such-root' not exists."}
    group = Group.objects.create(name="nats-r13-root", parent_id=0)
    found = nats_api.get_group_id("nats-r13-root")
    assert found == {"result": True, "data": group.id}
