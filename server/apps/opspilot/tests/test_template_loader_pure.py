"""TemplateLoader：按路径查找/渲染 Jinja 模板，缺失文件必须抛 TemplateNotFound。"""
from pathlib import Path

import pytest
from jinja2 import TemplateNotFound

from apps.opspilot.metis.utils.template_loader import TemplateLoader

pytestmark = pytest.mark.unit


@pytest.fixture
def templates_dir(tmp_path):
    TemplateLoader._env_cache.clear()
    TemplateLoader._default_base_path = None
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "greet.j2").write_text("你好 {{ name }}", encoding="utf-8")
    (tmp_path / "plain.txt").write_text("raw {{ value }}", encoding="utf-8")
    yield tmp_path
    TemplateLoader._env_cache.clear()
    TemplateLoader._default_base_path = None


def test_configure_sets_base_path_and_clears_env_cache(templates_dir):
    TemplateLoader.configure(str(templates_dir))
    TemplateLoader._get_environment()
    assert str(templates_dir) in TemplateLoader._env_cache
    TemplateLoader.configure(str(templates_dir / "prompts"))
    assert TemplateLoader._env_cache == {}


def test_render_template_resolves_prompts_prefix_and_j2_extension(templates_dir):
    rendered = TemplateLoader.render_template("greet", {"name": "BK"}, base_path=str(templates_dir))
    assert rendered == "你好 BK"


def test_load_template_with_context_returns_rendered_text(templates_dir):
    text = TemplateLoader.load_template("plain.txt", context={"value": "x"}, base_path=str(templates_dir))
    assert text == "raw x"


def test_load_template_without_context_returns_template_object(templates_dir):
    template = TemplateLoader.load_template("plain.txt", base_path=str(templates_dir))
    assert template.render(value="y") == "raw y"


def test_missing_template_raises_template_not_found(templates_dir):
    with pytest.raises(TemplateNotFound):
        TemplateLoader.render_template("does-not-exist", base_path=str(templates_dir))


def test_template_exists_and_list_templates(templates_dir):
    assert TemplateLoader.template_exists("greet", base_path=str(templates_dir)) is True
    assert TemplateLoader.template_exists("missing", base_path=str(templates_dir)) is False
    listed = TemplateLoader.list_templates(base_path=str(templates_dir))
    assert "prompts/greet" in listed
    assert "plain" in listed
