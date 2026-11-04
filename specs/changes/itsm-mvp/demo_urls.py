"""Local-only URL and authentication shell for the interactive ITSM demo."""

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.urls import include, path, re_path


TEAM_ID = 7
DEMO_USERS = [
    {"id": 101, "username": "demo-admin", "display_name": "演示管理员"},
    {"id": 102, "username": "manager-b", "display_name": "主管 B"},
    {"id": 201, "username": "security-a", "display_name": "安全专员 A"},
    {"id": 202, "username": "security-b", "display_name": "安全专员 B"},
    {"id": 301, "username": "handler", "display_name": "工单处理人"},
]


def success(data):
    return JsonResponse({"result": True, "data": data})


class DemoAuthMiddleware:
    """Authenticate every local demo request as the seeded superuser."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = get_user_model().objects.get(username="demo-admin", domain="domain.com")
        user.group_list = [TEAM_ID]
        user.group_tree = [{"id": TEAM_ID, "name": "研发部", "subGroups": []}]
        user.roles = ["itsm--admin"]
        user.permission = {"itsm": {"View", "Add", "Edit", "Publish", "Act", "Close"}}
        user.display_name = "演示管理员"
        user.timezone = "Asia/Shanghai"
        request.user = user
        if not request.COOKIES.get("current_team"):
            request._api_current_team = str(TEAM_ID)
        return self.get_response(request)


def login_info(_request):
    return success(
        {
            "user_id": 101,
            "username": "demo-admin",
            "display_name": "演示管理员",
            "is_superuser": True,
            "group_list": [{"id": TEAM_ID, "name": "研发部"}],
            "group_tree": [{"id": TEAM_ID, "name": "研发部", "subGroups": []}],
            "roles": ["itsm--admin"],
            "is_first_login": False,
            "locale": "zh-Hans",
            "timezone": "Asia/Shanghai",
        }
    )


def clients(_request):
    return success(
        [
            {
                "name": "itsm",
                "display_name": "ITSM",
                "url": "/itsm",
                "icon": "gongdan",
                "is_build_in": True,
            }
        ]
    )


def menus(_request):
    return success(
        [
            {"name": "catalog", "operation": ["View"]},
            {"name": "ticket", "operation": ["View", "Add", "Close"]},
            {"name": "todo", "operation": ["View", "Act"]},
            {"name": "service_management", "operation": ["View", "Add", "Edit", "Publish"]},
        ]
    )


def user_list(_request):
    return success({"users": DEMO_USERS, "count": len(DEMO_USERS)})


def login(_request):
    return success(
        {
            "id": 101,
            "username": "demo-admin",
            "token": "local-itsm-demo-token",
            "locale": "zh-Hans",
            "timezone": "Asia/Shanghai",
            "temporary_pwd": False,
            "enable_otp": False,
            "qrcode": False,
        }
    )


def empty(_request, *_args, **_kwargs):
    return success({})


urlpatterns = [
    path("api/v1/itsm/", include("apps.itsm.urls")),
    path("api/v1/core/api/login_info/", login_info),
    path("api/v1/core/api/login/", login),
    path("api/v1/core/api/get_client/", clients),
    path("api/v1/core/api/get_user_menus/", menus),
    path("api/v1/core/api/user_group/user_list/", user_list),
    path("api/v1/console_mgmt/user_app_sets/current_user_apps/", lambda request: success([])),
    path("api/v1/system_mgmt/custom_menu_group/get_menus/", lambda request: success({"is_build_in": True})),
    re_path(r"^api/v1/(core|console_mgmt|system_mgmt)/", empty),
]
