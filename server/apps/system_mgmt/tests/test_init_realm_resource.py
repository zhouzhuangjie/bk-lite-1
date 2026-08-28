"""init_realm_resource：菜单扩展、创建资源、默认角色。"""
import pytest

from apps.system_mgmt.management.commands.init_realm_resource import (
    create_default_roles,
    create_resource,
    extend_menus_by_install_apps,
)
from apps.system_mgmt.models import App, Menu, Role

pytestmark = pytest.mark.django_db


def test_extend_menus_skips_non_system_manager():
    data = {"client_id": "other", "menus": []}
    assert extend_menus_by_install_apps(data, {"license_mgmt"})["client_id"] == "other"


def test_extend_menus_adds_license_and_sensitive_info():
    data = {
        "client_id": "system-manager",
        "menus": [
            {"name": "Organization", "children": []},
            {"name": "Setting", "children": []},
        ],
        "roles": [{"name": "security", "menus": []}],
    }
    result = extend_menus_by_install_apps(data, {"license_mgmt"})
    setting = next(item for item in result["menus"] if item["name"] == "Setting")
    org = next(item for item in result["menus"] if item["name"] == "Organization")
    assert any(child["id"] == "license_mgmt" for child in setting["children"])
    assert any(child["id"] == "sensitive_info" for child in org["children"])
    security = next(item for item in result["roles"] if item["name"] == "security")
    assert "sensitive_info-View" in security["menus"]

    # 幂等：已存在则不再追加
    again = extend_menus_by_install_apps(result, {"license_mgmt"})
    setting2 = next(item for item in again["menus"] if item["name"] == "Setting")
    assert sum(1 for child in setting2["children"] if child["id"] == "license_mgmt") == 1


def test_create_resource_creates_updates_and_deletes_stale_menus():
    app = App.objects.create(name="demo-app", display_name="Demo", url="/demo")
    stale = Menu.objects.create(name="old-View", display_name="Old-View", app="demo-app", menu_type="Old")
    role = Role.objects.create(name="r1", app="demo-app", menu_list=[stale.id, 999])
    existing = Menu.objects.create(name="user-View", display_name="User-View-old", app="demo-app", menu_type="People")

    create_resource(
        app,
        [
            {
                "name": "People",
                "children": [
                    {"id": "user", "name": "User", "operation": ["View", "Edit"]},
                ],
            }
        ],
    )
    names = set(Menu.objects.filter(app="demo-app").values_list("name", flat=True))
    assert names == {"user-View", "user-Edit"}
    existing.refresh_from_db()
    assert existing.display_name == "User-View"
    role.refresh_from_db()
    assert stale.id not in role.menu_list
    assert 999 in role.menu_list


def test_create_default_roles_adds_manager_and_updates_existing():
    app = App.objects.create(name="role-app", display_name="Role", url="/r")
    view = Menu.objects.create(name="item-View", display_name="Item-View", app="role-app", menu_type="M")
    edit = Menu.objects.create(name="item-Edit", display_name="Item-Edit", app="role-app", menu_type="M")
    Role.objects.create(name="operator", app="role-app", menu_list=[])

    create_default_roles(
        app,
        [
            {"name": "operator", "menus": ["item-View"]},
            {"name": "auditor", "menus": ["item-Edit"]},
        ],
    )
    operator = Role.objects.get(name="operator", app="role-app")
    auditor = Role.objects.get(name="auditor", app="role-app")
    manager = Role.objects.get(name="manager", app="role-app")
    assert operator.menu_list == [view.id]
    assert auditor.menu_list == [edit.id]
    assert set(manager.menu_list) == {view.id, edit.id}
