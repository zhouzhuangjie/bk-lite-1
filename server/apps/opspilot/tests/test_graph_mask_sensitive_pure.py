"""graph SSE 输出脱敏：密码/token 等字段替换为 ***，不影响非敏感嵌套结构。"""
from apps.opspilot.metis.llm.chain.graph import _mask_sensitive_data

pytest_plugins = []


def test_mask_sensitive_data_redacts_nested_secrets_only():
    payload = {
        "password": "hunter2",
        "api_key": "sk-live",
        "token": "abc",
        "nested": {"secret": "s3cr3t", "name": "svc"},
        "items": [{"auth": "bearer-xyz", "id": 1}, "plain"],
        "empty_token": "",
        "count": 3,
    }
    masked = _mask_sensitive_data(payload)
    assert masked["password"] == "***"
    assert masked["api_key"] == "***"
    assert masked["token"] == "***"
    assert masked["nested"]["secret"] == "***"
    assert masked["nested"]["name"] == "svc"
    assert masked["items"][0]["auth"] == "***"
    assert masked["items"][0]["id"] == 1
    assert masked["items"][1] == "plain"
    assert masked["empty_token"] == ""
    assert masked["count"] == 3
    assert payload["password"] == "hunter2"
