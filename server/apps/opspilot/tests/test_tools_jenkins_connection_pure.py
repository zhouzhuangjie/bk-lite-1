"""Jenkins 凭据规范化与实例解析（对齐 ES connection 契约）。"""
import pytest

from apps.opspilot.metis.llm.tools.common.credentials import CredentialValidationError
from apps.opspilot.metis.llm.tools.jenkins import connection as jk

pytestmark = pytest.mark.unit


def test_parse_and_resolve_jenkins_instances():
    assert jk.parse_jenkins_instances(None) == []
    assert jk.parse_jenkins_instances("{nope") == []
    parsed = jk.parse_jenkins_instances('[{"name": "ci", "jenkins_url": "http://j:8080", "jenkins_username": "u"}]')
    assert parsed[0]["id"] == "jenkins-1"
    assert parsed[0]["name"] == "ci"
    with pytest.raises(ValueError, match="No Jenkins"):
        jk.resolve_jenkins_instance([])
    insts = [
        jk.normalize_jenkins_instance({"id": "a", "name": "A", "jenkins_url": "http://a"}),
        jk.normalize_jenkins_instance({"id": "b", "name": "B", "jenkins_url": "http://b"}),
    ]
    assert jk.resolve_jenkins_instance(insts, instance_id="b")["name"] == "B"
    assert jk.resolve_jenkins_instance(insts, instance_name="A")["id"] == "a"
    assert jk.resolve_jenkins_instance(insts, default_instance_id="b")["id"] == "b"
    with pytest.raises(ValueError, match="not found"):
        jk.resolve_jenkins_instance(insts, instance_id="missing")


def test_adapter_requires_url():
    adapter = jk.JenkinsCredentialAdapter()
    with pytest.raises(CredentialValidationError):
        adapter.validate({"jenkins_url": ""})
    adapter.validate({"jenkins_url": "http://j"})
    cfg = adapter.build_from_flat_config({"jenkins_url": "http://j", "jenkins_username": "u", "jenkins_password": "p"})
    assert cfg["jenkins_url"] == "http://j"
