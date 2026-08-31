"""Jenkins connection 剩余：非 list 解析、跳过非 dict、normalized 凭据、连通性探测、实例提示。"""
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.metis.llm.tools.jenkins import connection as jk

pytestmark = pytest.mark.unit


def test_parse_skips_non_list_and_non_dict_items():
    assert jk.parse_jenkins_instances({"name": "ci"}) == []
    parsed = jk.parse_jenkins_instances([{"name": "ci", "jenkins_url": "http://j"}, "skip-me", None])
    assert len(parsed) == 1
    assert parsed[0]["id"] == "jenkins-1"
    assert parsed[0]["name"] == "ci"


def test_get_instances_from_configurable_and_resolve_name_miss():
    instances, default_id = jk.get_jenkins_instances_from_configurable(
        {
            "jenkins_instances": '[{"id": "a", "name": "A", "jenkins_url": "http://a"}]',
            "jenkins_default_instance_id": "a",
        }
    )
    assert default_id == "a"
    assert instances[0]["id"] == "a"
    with pytest.raises(ValueError, match="not found: missing"):
        jk.resolve_jenkins_instance(instances, instance_name="missing")
    assert jk.resolve_jenkins_instance(instances, default_instance_id="gone")["id"] == "a"


def test_build_normalized_single_multi_and_legacy():
    single = jk.build_jenkins_normalized_from_runnable(
        {
            "configurable": {
                "jenkins_instances": '[{"id": "a", "name": "A", "jenkins_url": "http://a"}]',
            }
        }
    )
    assert single["mode"] == "single"
    assert single["legacy_single"] is False
    assert single["items"][0]["config"]["jenkins_url"] == "http://a"

    targeted = jk.build_jenkins_normalized_from_runnable(
        {
            "configurable": {
                "jenkins_instances": (
                    '[{"id": "a", "name": "A", "jenkins_url": "http://a"},'
                    '{"id": "b", "name": "B", "jenkins_url": "http://b"}]'
                ),
                "jenkins_default_instance_id": "a",
            }
        },
        instance_id="b",
    )
    assert targeted["mode"] == "single"
    assert targeted["items"][0]["name"] == "B"

    multi = jk.build_jenkins_normalized_from_runnable(
        {
            "configurable": {
                "jenkins_instances": (
                    '[{"id": "a", "name": "A", "jenkins_url": "http://a"},'
                    '{"id": "b", "name": "B", "jenkins_url": "http://b"}]'
                )
            }
        }
    )
    assert multi["mode"] == "multi"
    assert len(multi["items"]) == 2

    legacy = jk.build_jenkins_normalized_from_runnable(
        {"configurable": {"jenkins_url": "http://legacy", "jenkins_username": "u", "jenkins_password": "p"}}
    )
    assert legacy["items"][0]["config"]["jenkins_url"] == "http://legacy"


def test_test_jenkins_instance_requires_url_and_pings_jobs():
    with pytest.raises(ValueError, match="Jenkins URL is required"):
        jk.test_jenkins_instance({"jenkins_url": ""})
    client = MagicMock()
    with patch.object(jk.jenkins, "Jenkins", return_value=client) as ctor:
        assert jk.test_jenkins_instance({"jenkins_url": "http://ci", "jenkins_username": "u", "jenkins_password": "p"}) is True
    ctor.assert_called_once_with("http://ci", username="u", password="p")
    client.get_jobs.assert_called_once_with()


def test_instances_prompt_empty_and_default_instance():
    assert jk.get_jenkins_instances_prompt({}) == ""
    prompt = jk.get_jenkins_instances_prompt(
        {
            "jenkins_instances": (
                '[{"id": "a", "name": "Alpha", "jenkins_url": "http://a"},'
                '{"id": "b", "name": "Beta", "jenkins_url": "http://b"}]'
            ),
            "jenkins_default_instance_id": "b",
        }
    )
    assert "已配置 2 个 Jenkins 实例" in prompt
    assert "可用实例: Alpha, Beta" in prompt
    assert "默认实例为「Beta」" in prompt


def test_adapter_display_name_and_credential_item():
    adapter = jk.JenkinsCredentialAdapter()
    assert adapter.get_display_name({}, 2) == "Jenkins - 3"
    assert adapter.get_display_name({"name": "CI"}, 0) == "CI"
    cfg = adapter.build_from_credential_item({"jenkins_url": "http://j", "name": "CI"})
    assert cfg == {"jenkins_url": "http://j", "jenkins_username": "", "jenkins_password": ""}
