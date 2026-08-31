"""技能包 runtime 剩余：JSON 规范化、hydrate 回填、manifest 磁盘覆盖。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.opspilot.models import SkillPackage
from apps.opspilot.services.skill_package import runtime as rt

pytestmark = pytest.mark.django_db


def test_normalize_skill_packages_json_string_and_invalid():
    assert rt.normalize_skill_packages(None) == []
    assert rt.normalize_skill_packages("not-json") == []
    assert rt.normalize_skill_packages({"id": 1}) == []
    assert rt.normalize_skill_packages('[{"id": 1}, "x"]') == [{"id": 1}]


def test_message_to_text_dict_list_and_other():
    assert rt._message_to_text("") == ""
    assert rt._message_to_text({"content": ["a", {"content": "b"}]}) == "a b"
    assert rt._message_to_text({"content": 3}) == "3"
    assert rt._message_to_text({"x": "keep", "y": ""}) == "keep"
    assert rt._message_to_text(["hello", 1]) == "hello 1"
    assert rt._message_to_text(9) == "9"


def test_hydrate_skill_packages_overlays_enabled_record():
    stored = SkillPackage.objects.create(
        package_id="k8s",
        name="K8s 专家",
        version="1.0.0",
        description="排查",
        category="ops",
        skill_markdown="# k8s",
        required_tools=["kubectl"],
        triggers=["k8s"],
        manifest={"capabilities": ["rca"], "reports": {"a": 1}, "workflows": {"w": 2}},
        is_enabled=True,
        created_by="admin",
        domain="domain.com",
    )
    SkillPackage.objects.create(
        package_id="off",
        name="关闭",
        version="1.0.0",
        is_enabled=False,
        created_by="admin",
        domain="domain.com",
    )
    out = rt.hydrate_skill_packages(
        [{"id": stored.id, "name": "old"}, {"id": 999999, "name": "missing"}, {"name": "no-id"}]
    )
    assert out[0]["name"] == "K8s 专家"
    assert out[0]["package_id"] == "k8s"
    assert out[0]["capabilities"] == ["rca"]
    assert out[0]["skill_markdown"] == "# k8s"
    assert out[1] == {"id": 999999, "name": "missing"}
    assert out[2] == {"name": "no-id"}


def test_hydrate_returns_original_when_queryset_fails():
    with patch.object(SkillPackage.objects, "filter", side_effect=RuntimeError("db down")):
        assert rt.hydrate_skill_packages([{"id": 1, "name": "keep"}]) == [{"id": 1, "name": "keep"}]


def test_manifest_with_storage_overlay_reads_yaml(tmp_path):
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "skill.yaml").write_text(
        "capabilities:\n  - disk\nreports:\n  r: 1\nworkflows:\n  w: 2\n",
        encoding="utf-8",
    )
    stored = SimpleNamespace(manifest={"name": "p"}, storage_path=str(tmp_path))
    out = rt._manifest_with_storage_overlay(stored)
    assert out["capabilities"] == ["disk"]
    assert out["reports"] == {"r": 1}
    assert out["workflows"] == {"w": 2}
    assert out["name"] == "p"

    stored_ok = SimpleNamespace(
        manifest={"capabilities": [], "reports": {}, "workflows": {}},
        storage_path=str(tmp_path),
    )
    assert rt._manifest_with_storage_overlay(stored_ok) == stored_ok.manifest

    stored.storage_path = str(tmp_path / "missing")
    stored.manifest = {}
    assert rt._manifest_with_storage_overlay(stored) == {}
