import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Route, TimeoutError as PlaywrightTimeoutError, sync_playwright


OUTPUT = Path(__file__).with_name("evidence")
OUTPUT.mkdir(exist_ok=True)

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "title": "申请摘要", "maxLength": 120, "x-widget": "input"},
        "description": {"type": "string", "title": "申请说明", "maxLength": 2000, "x-widget": "textarea"},
    },
    "required": ["summary"],
    "additionalProperties": False,
}
WORKFLOW = {
    "schemaVersion": 1,
    "stages": [
        {
            "key": "manager",
            "name": "主管审批",
            "mode": "serial",
            "approverIds": [101, 102],
            "allowBeforeSign": True,
            "allowAfterSign": True,
        },
        {
            "key": "security",
            "name": "安全会签",
            "mode": "parallel",
            "approverIds": [201, 202],
            "allowBeforeSign": False,
            "allowAfterSign": False,
        },
    ],
    "handlerIds": [301],
}
SERVICE = {
    "id": 1,
    "name": "数据库资源申请",
    "description": "申请生产数据库及账号权限",
    "team_id": 7,
    "status": "PUBLISHED",
    "form_schema": SCHEMA,
    "workflow_config": WORKFLOW,
    "draft_revision": 3,
    "last_published_revision": 3,
    "current_version": 2,
    "has_draft": False,
    "created_by": "admin",
    "updated_by": "admin",
    "created_at": "2026-11-03T08:00:00Z",
    "updated_at": "2026-11-03T09:00:00Z",
}
USERS = [
    {"id": 101, "username": "manager-a", "display_name": "主管 A"},
    {"id": 102, "username": "manager-b", "display_name": "主管 B"},
    {"id": 901, "username": "signer", "display_name": "加签人"},
]
TICKET = {
    "id": "ticket-1",
    "number": "ITSM-20261103-0001",
    "service_id": 1,
    "service_name": SERVICE["name"],
    "service_version_number": 2,
    "form_schema": SCHEMA,
    "workflow_config": WORKFLOW,
    "requester_user_id": 88,
    "requester_username": "alice",
    "form_data": {"summary": "生产订单库扩容", "description": "容量提升至 500 GB"},
    "status": "APPROVING",
    "resolved_at": None,
    "closed_at": None,
    "created_at": "2026-11-03T09:00:00Z",
    "updated_at": "2026-11-03T09:05:00Z",
    "audit_events": [
        {
            "id": 1,
            "actor_user_id": 88,
            "actor_username": "alice",
            "action": "SUBMIT_REQUESTED",
            "from_status": "",
            "to_status": "APPROVING",
            "reason": "",
            "detail": {},
            "created_at": "2026-11-03T09:00:00Z",
        }
    ],
}


def envelope(data):
    return {"result": True, "data": data}


def respond(route: Route) -> None:
    path = urlparse(route.request.url).path
    if path.endswith("/core/api/get_bk_settings/"):
        payload = {"result": False, "data": {}}
    elif path.endswith("/core/api/login_info/"):
        group = {"id": 7, "name": "研发部", "subGroups": []}
        payload = envelope(
            {
                "group_list": [group],
                "group_tree": [group],
                "roles": ["itsm_admin"],
                "is_superuser": True,
                "is_first_login": False,
                "user_id": 101,
                "username": "manager-a",
                "display_name": "主管 A",
            }
        )
    elif path.endswith("/core/api/user_group/user_list/"):
        payload = envelope({"users": USERS, "count": len(USERS)})
    elif path.endswith("/core/api/get_client/"):
        payload = envelope(
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
    elif path.endswith("/console_mgmt/user_app_sets/current_user_apps/"):
        payload = envelope([])
    elif path.endswith("/core/api/get_user_menus/"):
        payload = envelope(
            [
                {"name": "catalog", "operation": ["View"]},
                {"name": "ticket", "operation": ["View", "Add", "Close"]},
                {"name": "todo", "operation": ["View", "Act"]},
                {"name": "service_management", "operation": ["View", "Add", "Edit", "Publish"]},
            ]
        )
    elif path.endswith("/system_mgmt/custom_menu_group/get_menus/"):
        payload = envelope({"is_build_in": True})
    elif path.endswith("/itsm/api/services/1/"):
        payload = envelope(SERVICE)
    elif path.endswith("/itsm/api/services/"):
        payload = envelope({"count": 1, "items": [SERVICE]})
    elif path.endswith("/itsm/api/tasks/"):
        payload = envelope(
            {
                "count": 1,
                "items": [
                    {
                        "id": "task-1",
                        "ticket_id": "ticket-1",
                        "ticket_number": "ITSM-20261103-0001",
                        "service_name": SERVICE["name"],
                        "requester_username": "alice",
                        "ticket_status": "APPROVING",
                        "form_data": {"summary": "生产订单库扩容", "description": "容量提升至 500 GB"},
                        "form_schema": SCHEMA,
                        "task_type": "APPROVAL",
                        "title": "主管审批",
                        "status": "PENDING",
                        "stage_key": "manager",
                        "allow_before_sign": True,
                        "allow_after_sign": True,
                        "sign_parent_key": "",
                        "created_at": "2026-11-03T09:00:00Z",
                        "updated_at": "2026-11-03T09:00:00Z",
                    }
                ],
            }
        )
    elif path.endswith("/itsm/api/tickets/ticket-1/"):
        payload = envelope(TICKET)
    elif path.endswith("/itsm/api/tickets/"):
        payload = envelope({"count": 1, "items": [TICKET]})
    elif path.endswith("/itsm/api/catalog/1/"):
        payload = envelope({key: SERVICE[key] for key in ("id", "name", "description", "team_id", "current_version", "form_schema", "workflow_config", "updated_at")})
    elif path.endswith("/itsm/api/catalog/"):
        catalog = {key: SERVICE[key] for key in ("id", "name", "description", "team_id", "current_version", "form_schema", "workflow_config", "updated_at")}
        payload = envelope({"count": 1, "items": [catalog]})
    else:
        payload = envelope({})
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))


def navigate(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        # The BK-Lite shell keeps authentication/recovery requests alive in development mode.
        pass


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.add_init_script("localStorage.setItem('locale', 'zh-Hans')")
    page.route("**/api/proxy/**", respond)
    page.route(
        "**/api/auth/recovery-check",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "authenticated": True,
                    "user": {
                        "id": "101",
                        "username": "manager-a",
                        "token": "ui-verification-token",
                        "locale": "zh-Hans",
                        "timezone": "Asia/Shanghai",
                    },
                }
            ),
        ),
    )
    console_errors: list[str] = []
    response_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("response", lambda response: response_errors.append(f"{response.status} {response.url}") if response.status >= 400 else None)

    csrf_response = page.request.get("http://127.0.0.1:13000/api/auth/csrf", timeout=30_000)
    csrf_token = csrf_response.json()["csrfToken"]
    auth_response = page.request.post(
        "http://127.0.0.1:13000/api/auth/callback/credentials?json=true",
        form={
            "csrfToken": csrf_token,
            "callbackUrl": "http://127.0.0.1:13000/itsm/services",
            "username": "manager-a",
            "password": "",
            "skipValidation": "true",
            "userData": json.dumps(
                {
                    "id": 101,
                    "username": "manager-a",
                    "token": "ui-verification-token",
                    "locale": "zh-Hans",
                    "timezone": "Asia/Shanghai",
                }
            ),
        },
        timeout=30_000,
    )
    if not auth_response.ok:
        raise AssertionError(f"NextAuth setup failed: {auth_response.status} {auth_response.text()}")
    session_response = page.request.get("http://127.0.0.1:13000/api/auth/session", timeout=30_000)
    if not session_response.ok:
        raise AssertionError(f"NextAuth session failed: {session_response.status}")

    navigate(page, "http://127.0.0.1:13000/itsm/services")
    try:
        page.get_by_text("数据库资源申请").first.wait_for(timeout=8_000)
    except PlaywrightTimeoutError:
        page.screenshot(path=str(OUTPUT / "itsm-ui-debug.png"), full_page=True)
        raise AssertionError(f"Service page did not render. URL={page.url}; responses={response_errors}; console={console_errors}")
    page.screenshot(path=str(OUTPUT / "itsm-ui-services.png"), full_page=True)

    navigate(page, "http://127.0.0.1:13000/itsm/catalog")
    page.get_by_text("数据库资源申请").first.wait_for(timeout=30_000)
    page.screenshot(path=str(OUTPUT / "itsm-ui-catalog.png"), full_page=True)

    navigate(page, "http://127.0.0.1:13000/itsm/services/1")
    page.get_by_text("流程设计").click()
    page.get_by_text("允许前加签").first.wait_for(timeout=30_000)
    page.get_by_role("button", name="添加审批节点").wait_for()
    page.screenshot(path=str(OUTPUT / "itsm-ui-service-editor.png"), full_page=True)

    navigate(page, "http://127.0.0.1:13000/itsm/tickets?view=todo")
    page.get_by_text("ITSM-20261103-0001").wait_for(timeout=30_000)
    page.screenshot(path=str(OUTPUT / "itsm-ui-todo.png"), full_page=True)

    navigate(page, "http://127.0.0.1:13000/itsm/catalog/1")
    page.get_by_label("申请摘要").fill("申请新的生产数据库")
    page.get_by_label("申请说明").fill("用于订单服务灰度发布")
    page.screenshot(path=str(OUTPUT / "itsm-ui-ticket-submit.png"), full_page=True)

    navigate(page, "http://127.0.0.1:13000/itsm/tickets/ticket-1")
    page.get_by_text("申请内容").first.wait_for(timeout=30_000)
    page.screenshot(path=str(OUTPUT / "itsm-ui-ticket-detail.png"), full_page=True)
    page.get_by_role("button", name="查看流程图").first.click()
    page.get_by_text("流程图画布").wait_for(timeout=10_000)
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUTPUT / "itsm-ui-ticket-flow-drawer.png"), full_page=True)

    navigate(page, "http://127.0.0.1:13000/itsm/tickets")
    page.get_by_text("ITSM-20261103-0001").wait_for(timeout=30_000)
    page.screenshot(path=str(OUTPUT / "itsm-ui-tickets.png"), full_page=True)

    page.evaluate("localStorage.setItem('theme', 'dark')")
    navigate(page, "http://127.0.0.1:13000/itsm/tickets/ticket-1")
    page.get_by_text("申请内容").first.wait_for(timeout=30_000)
    page.screenshot(path=str(OUTPUT / "itsm-ui-ticket-detail-dark.png"), full_page=True)

    relevant_errors = [item for item in console_errors if "<path> attribute d" not in item and "favicon" not in item]
    if relevant_errors:
        raise AssertionError(f"Browser console errors: {relevant_errors}")
    print("UI verification passed: catalog, services, editor, todo, before-sign drawer, ticket submission, ticket list/detail")
    browser.close()
