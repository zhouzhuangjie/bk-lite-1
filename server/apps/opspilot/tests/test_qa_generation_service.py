"""QAGeneration：转义花括号、SSRF 校验 LLM 端点、三条生成链解析 JSON。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.metis.llm.rag.enhance.qa_generation import QAGeneration
from apps.opspilot.metis.llm.rag.rag_enhance_entity import (
    AnswerGenerateRequest,
    QAEnhanceRequest,
    QuestionGenerateRequest,
)

pytestmark = pytest.mark.unit
MOD = "apps.opspilot.metis.llm.rag.enhance.qa_generation"


class _FakeChain:
    def __init__(self, content):
        self._content = content

    def __or__(self, _other):
        return self

    def invoke(self, _payload):
        return SimpleNamespace(content=self._content)


def _run(method, req, parsed):
    with (
        patch(f"{MOD}.TemplateLoader") as loader,
        patch(f"{MOD}.ChatOpenAI", return_value=MagicMock()),
        patch(f"{MOD}.ChatPromptTemplate") as prompt_cls,
        patch(f"{MOD}.SSRFValidator") as ssrf,
        patch(f"{MOD}.json_repair") as jr,
    ):
        loader.render_template.return_value = "rendered"
        prompt_cls.from_messages.return_value = _FakeChain('{"ok": true}')
        jr.loads.return_value = parsed
        out = method(req)
    return out, ssrf, jr, loader


def test_escape_template_braces_doubles_curly_and_keeps_empty():
    assert QAGeneration._escape_template_braces("") == ""
    assert QAGeneration._escape_template_braces(None) is None
    assert QAGeneration._escape_template_braces("a{b}c") == "a{{b}}c"


def test_generate_answer_validates_endpoint_and_parses_json():
    req = AnswerGenerateRequest(
        context="ctx {x}",
        content="q {y}",
        extra_prompt="p {z}",
        openai_api_base="https://llm.internal/v1",
        openai_api_key="k",
        model="gpt-4o",
    )
    out, ssrf, jr, loader = _run(QAGeneration.generate_answer, req, {"answer": "yes"})
    assert out == {"answer": "yes"}
    ssrf.validate_llm_endpoint.assert_called_once_with("https://llm.internal/v1")
    jr.loads.assert_called_once_with('{"ok": true}')
    contexts = [c.kwargs.get("context") for c in loader.render_template.call_args_list if c.kwargs.get("context")]
    assert contexts[0]["context"] == "ctx {{x}}"
    assert contexts[0]["text"] == "q {{y}}"
    assert contexts[0]["extra_prompt"] == "p {{z}}"


def test_generate_question_skips_ssrf_when_base_empty():
    req = QuestionGenerateRequest(
        content="doc",
        size=2,
        openai_api_base="",
        extra_prompt="",
    )
    out, ssrf, jr, _ = _run(QAGeneration.generate_question, req, [{"question": "q1"}])
    assert out == [{"question": "q1"}]
    ssrf.validate_llm_endpoint.assert_not_called()
    jr.loads.assert_called_once_with('{"ok": true}')


def test_generate_qa_validates_endpoint():
    req = QAEnhanceRequest(
        content="pair",
        size=1,
        openai_api_base="http://127.0.0.1:8000/v1",
    )
    out, ssrf, _, _ = _run(QAGeneration.generate_qa, req, [{"q": "a"}])
    assert out == [{"q": "a"}]
    ssrf.validate_llm_endpoint.assert_called_once_with("http://127.0.0.1:8000/v1")
