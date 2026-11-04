from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

import httpx

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_QUERY_ROWS = 2000
AMBIGUOUS_STATUS_CODES = {408, 409, 429}


class FlowableConfigurationError(ValueError):
    pass


class FlowableUnavailable(RuntimeError):
    pass


class FlowableConnectionUnavailable(FlowableUnavailable):
    """连接建立前失败，远端可以确定没有收到请求。"""


class FlowableRejected(RuntimeError):
    pass


class FlowableOutcomeUnknown(FlowableUnavailable):
    pass


def variable(name: str, value: Any, *, local: bool = False) -> dict[str, Any]:
    if isinstance(value, bool):
        value_type = "boolean"
    elif isinstance(value, int):
        value_type = "integer"
    elif isinstance(value, (list, dict)):
        value_type = "json"
    else:
        value_type = "string"
    result = {"name": name, "value": value, "type": value_type}
    if local:
        result["scope"] = "local"
    return result


class FlowableClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
        transport=None,
        timeout: float = 10.0,
    ):
        raw_url = (base_url or os.getenv("FLOWABLE_REST_URL", "http://flowable-rest:8080/flowable-rest/service")).rstrip("/")
        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise FlowableConfigurationError("FLOWABLE_REST_URL 必须是无内嵌凭据的 http(s) 服务地址")
        if parsed.query or parsed.fragment or not parsed.path.endswith("/service"):
            raise FlowableConfigurationError("FLOWABLE_REST_URL 必须指向 Flowable REST service 根路径")
        resolved_username = username if username is not None else os.getenv("FLOWABLE_REST_USER", "")
        resolved_password = password if password is not None else os.getenv("FLOWABLE_REST_PASSWORD", "")
        if not resolved_username or not resolved_password:
            raise FlowableConfigurationError("Flowable REST 凭据必须由运行环境注入")

        self.base_url = raw_url
        self._client = httpx.Client(
            auth=(resolved_username, resolved_password),
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
            transport=transport,
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, *, allowed_statuses: set[int] | None = None, **kwargs) -> httpx.Response:
        try:
            response = self._client.request(method, f"{self.base_url}{path}", **kwargs)
            if response.status_code >= 400 and response.status_code not in (allowed_statuses or set()):
                response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                raise FlowableUnavailable("Flowable REST 响应超过大小上限")
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise FlowableUnavailable("Flowable REST 响应超过大小上限")
            return response
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            if 400 <= status_code < 500 and status_code not in AMBIGUOUS_STATUS_CODES:
                raise FlowableRejected("Flowable 明确拒绝了请求") from error
            raise FlowableUnavailable("Flowable 服务不可用或响应不确定") from error
        except httpx.ConnectError as error:
            raise FlowableConnectionUnavailable("无法连接 Flowable 服务") from error
        except httpx.HTTPError as error:
            raise FlowableUnavailable("Flowable 服务不可用或响应不确定") from error

    def _json(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        response = self._request(method, path, **kwargs)
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as error:
            raise FlowableUnavailable("Flowable REST 返回了非法 JSON") from error
        if not isinstance(payload, dict):
            raise FlowableUnavailable("Flowable REST 返回结构异常")
        return payload

    def _list(self, method: str, path: str, *, allow_not_found: bool = False, **kwargs) -> list[Any]:
        response = self._request(method, path, allowed_statuses={404} if allow_not_found else None, **kwargs)
        if response.status_code == 404 or not response.content:
            return []
        try:
            payload = response.json()
        except ValueError as error:
            raise FlowableUnavailable("Flowable REST 返回了非法 JSON") from error
        if not isinstance(payload, list):
            raise FlowableUnavailable("Flowable REST 返回结构异常")
        return payload

    def rows(self, path: str, **params) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        while len(rows) < MAX_QUERY_ROWS:
            payload = self._json("GET", path, params={**params, "start": len(rows), "size": 100})
            page = payload.get("data")
            if not isinstance(page, list):
                raise FlowableUnavailable("Flowable REST 分页结构异常")
            rows.extend(item for item in page if isinstance(item, dict))
            total = payload.get("total")
            if not page or isinstance(total, int) and len(rows) >= total:
                return rows
        raise FlowableUnavailable("Flowable REST 查询结果超过上限")

    def deploy_archive(self, name: str, archive: bytes, *, process_key: str) -> dict[str, str]:
        deployment = self._json(
            "POST",
            "/repository/deployments",
            files={"file": ("itsm-processes.zip", archive, "application/zip")},
            data={"name": name},
        )
        deployment_id = str(deployment.get("id") or "")
        if not deployment_id:
            raise FlowableUnavailable("Flowable 未返回 deployment id")
        definitions = self.rows("/repository/process-definitions", deploymentId=deployment_id)
        matched = [item for item in definitions if item.get("key") == process_key]
        if len(matched) != 1 or not matched[0].get("id"):
            raise FlowableUnavailable("无法唯一解析已部署的流程定义")
        return {"deployment_id": deployment_id, "process_definition_id": str(matched[0]["id"])}

    def find_deployment(self, name: str, *, process_key: str) -> dict[str, str] | None:
        deployments = [item for item in self.rows("/repository/deployments", name=name) if item.get("name") == name]
        if not deployments:
            return None
        if len(deployments) != 1 or not deployments[0].get("id"):
            raise FlowableOutcomeUnknown("同名 Flowable 部署不唯一，需要人工核对")
        deployment_id = str(deployments[0]["id"])
        definitions = self.rows("/repository/process-definitions", deploymentId=deployment_id)
        matched = [item for item in definitions if item.get("key") == process_key and item.get("id")]
        if len(matched) != 1:
            raise FlowableOutcomeUnknown("Flowable 部署存在但流程定义无法唯一解析")
        return {"deployment_id": deployment_id, "process_definition_id": str(matched[0]["id"])}

    def start_process(self, process_definition_id: str, *, business_key: str, variables: list[dict[str, Any]]) -> dict[str, Any]:
        return self._json(
            "POST",
            "/runtime/process-instances",
            json={"processDefinitionId": process_definition_id, "businessKey": business_key, "variables": variables},
        )

    def complete_task(self, task_id: str, *, variables: list[dict[str, Any]]) -> None:
        self._request("POST", f"/runtime/tasks/{task_id}", json={"action": "complete", "variables": variables})

    def historic_processes(self, *, business_key: str) -> list[dict[str, Any]]:
        return self.rows("/history/historic-process-instances", businessKey=business_key)

    def historic_receipt(self, variable_name: str) -> str | None:
        rows = self.rows("/history/historic-variable-instances", variableName=variable_name)
        if not rows:
            return None
        if len(rows) != 1:
            raise FlowableOutcomeUnknown("Flowable 命令回执不唯一，需要人工核对")
        variable_data = rows[0].get("variable")
        if not isinstance(variable_data, dict):
            return None
        value = variable_data.get("value")
        return str(value) if value is not None else None

    def task_exists(self, task_id: str) -> bool:
        response = self._request("GET", f"/runtime/tasks/{task_id}", allowed_statuses={404})
        return response.status_code != 404

    def active_tasks(self, root_process_instance_id: str) -> list[dict[str, Any]]:
        process_ids = [root_process_instance_id]
        variables_by_process: dict[str, dict[str, Any]] = {}
        tasks: list[dict[str, Any]] = []
        for process_id in process_ids:
            children = self.rows("/history/historic-process-instances", superProcessInstanceId=process_id)
            for child in children:
                child_id = child.get("id")
                if child_id and child_id not in process_ids:
                    process_ids.append(str(child_id))
            if len(process_ids) > 200:
                raise FlowableUnavailable("工单流程实例数量超过上限")

            raw_variables = self._list(
                "GET",
                f"/runtime/process-instances/{process_id}/variables",
                allow_not_found=True,
            )
            variables_by_process[process_id] = {
                str(item["name"]): item.get("value") for item in raw_variables if isinstance(item, dict) and item.get("name")
            }
            for task in self.rows("/runtime/tasks", processInstanceId=process_id):
                variables = variables_by_process[process_id]
                tasks.append(
                    {
                        "id": str(task.get("id") or ""),
                        "process_instance_id": process_id,
                        "definition_key": str(task.get("taskDefinitionKey") or ""),
                        "name": str(task.get("name") or ""),
                        "assignee": str(task.get("assignee") or ""),
                        "stage_key": str(variables.get("stageKey") or ""),
                        "depth": int(variables.get("depth") or 0),
                        "allow_before_sign": bool(variables.get("allowBeforeSign", False)),
                        "allow_after_sign": bool(variables.get("allowAfterSign", False)),
                    }
                )
        return tasks

    def process_result(self, process_instance_id: str) -> str:
        history = self._json("GET", f"/history/historic-process-instances/{process_instance_id}")
        if not history.get("endTime"):
            return "running"
        variables = self.rows(
            "/history/historic-variable-instances",
            processInstanceId=process_instance_id,
            excludeTaskVariables="true",
        )
        values: dict[str, Any] = {}
        for item in variables:
            variable_data = item.get("variable")
            if isinstance(variable_data, dict) and variable_data.get("name"):
                values[str(variable_data["name"])] = variable_data.get("value")
        return "rejected" if values.get("approved") is False else "completed"
