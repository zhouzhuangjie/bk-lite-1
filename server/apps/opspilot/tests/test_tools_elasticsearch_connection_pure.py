"""Elasticsearch 凭据规范化、实例解析与客户端参数构建。"""
from unittest.mock import MagicMock, patch

import pytest
from apps.opspilot.metis.llm.tools.common.credentials import CredentialValidationError
from apps.opspilot.metis.llm.tools.elasticsearch import connection as es


pytestmark = pytest.mark.unit


def test_normalize_bool_and_instance_defaults():
    assert es._normalize_bool(True) is True
    assert es._normalize_bool("false") is False
    assert es._normalize_bool("0") is False
    assert es._normalize_bool(None) is True
    inst = es.normalize_es_instance({})
    assert inst["url"] == "http://127.0.0.1:9200"
    assert inst["id"] == "es-1"
    assert inst["verify_certs"] is True


def test_parse_es_instances_json_and_invalid():
    assert es.parse_es_instances(None) == []
    assert es.parse_es_instances("{not json") == []
    assert es.parse_es_instances({"url": "x"}) == []
    raw = '[{"name": "prod", "url": "http://es:9200", "verify_certs": "false"}, "skip"]'
    parsed = es.parse_es_instances(raw)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "prod"
    assert parsed[0]["verify_certs"] is False
    assert parsed[0]["id"] == "es-1"


def test_resolve_es_instance_by_id_name_default_and_errors():
    insts = [
        es.normalize_es_instance({"id": "a", "name": "alpha", "url": "http://a"}),
        es.normalize_es_instance({"id": "b", "name": "beta", "url": "http://b"}),
    ]
    with pytest.raises(ValueError, match="No Elasticsearch"):
        es.resolve_es_instance([])
    assert es.resolve_es_instance(insts, instance_id="b")["name"] == "beta"
    assert es.resolve_es_instance(insts, instance_name="alpha")["id"] == "a"
    with pytest.raises(ValueError, match="not found: missing"):
        es.resolve_es_instance(insts, instance_id="missing")
    with pytest.raises(ValueError, match="not found: ghost"):
        es.resolve_es_instance(insts, instance_name="ghost")
    assert es.resolve_es_instance(insts, default_instance_id="b")["id"] == "b"
    assert es.resolve_es_instance(insts)["id"] == "a"


def test_build_es_client_kwargs_auth_and_tls():
    api = es._build_es_client_kwargs({"url": "http://es", "api_key": "k", "verify_certs": False})
    assert api["api_key"] == "k"
    assert "http_auth" not in api
    basic = es._build_es_client_kwargs({"url": "http://es", "username": "u", "password": "p", "ca_certs": "/ca", "client_cert": "c", "client_key": "k"})
    assert basic["http_auth"] == ("u", "p")
    assert basic["ca_certs"] == "/ca"
    assert basic["client_cert"] == "c"


def test_adapter_validate_and_display_name():
    adapter = es.ESCredentialAdapter()
    with pytest.raises(CredentialValidationError, match="URL is required"):
        adapter.validate({"url": ""})
    adapter.validate({"url": "http://es"})
    assert adapter.get_display_name({"name": "n"}, 0) == "n"
    assert adapter.get_display_name({}, 2) == "Elasticsearch - 3"


def test_build_normalized_from_runnable_multi_and_legacy():
    cfg = {
        "configurable": {
            "es_instances": [
                {"id": "a", "name": "A", "url": "http://a"},
                {"id": "b", "name": "B", "url": "http://b"},
            ],
            "es_default_instance_id": "b",
        }
    }
    multi = es.build_es_normalized_from_runnable(cfg)
    assert multi["mode"] == "multi"
    assert len(multi["items"]) == 2
    named = es.build_es_normalized_from_runnable(cfg, instance_name="A")
    assert named["mode"] == "single"
    assert named["items"][0]["name"] == "A"
    legacy = es.build_es_normalized_from_runnable({"configurable": {"url": "http://legacy", "username": "u"}})
    assert legacy["legacy_single"] is True
    assert legacy["items"][0]["config"]["url"] == "http://legacy"


def test_instances_prompt_and_legacy_config():
    prompt = es.get_es_instances_prompt(
        {"es_instances": [{"id": "a", "name": "prod", "url": "http://a"}], "es_default_instance_id": "a"}
    )
    assert "prod" in prompt
    assert "默认实例" in prompt
    assert es.get_es_instances_prompt({}) == ""
    kwargs = es.build_es_config_from_runnable({"configurable": {"url": "http://x", "api_key": "k"}})
    assert kwargs["hosts"] == ["http://x"]
    assert kwargs["api_key"] == "k"


def test_test_es_instance_ping_and_close():
    client = MagicMock()
    client.ping.return_value = True
    with patch.object(es, "Elasticsearch", return_value=client) as ctor:
        assert es.test_es_instance({"url": "http://es"}) is True
    ctor.assert_called_once()
    client.close.assert_called_once()

    client.ping.return_value = False
    with patch.object(es, "Elasticsearch", return_value=client):
        with pytest.raises(ConnectionError, match="ping returned False"):
            es.test_es_instance({"url": "http://es"})
