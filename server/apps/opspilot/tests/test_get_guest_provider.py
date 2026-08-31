"""get_guest_provider：把内置模型加入目标组织并返回 id/name。"""
import pytest

from apps.opspilot.models import EmbedProvider, LLMModel, OCRProvider, RerankProvider
from apps.opspilot.nats_api import get_guest_provider

pytestmark = pytest.mark.django_db


def _builtin(model, name, team=None):
    obj, _ = model.objects.get_or_create(name=name, defaults={"is_build_in": True, "team": list(team or [])})
    obj.is_build_in = True
    if team is not None:
        obj.team = list(team)
        obj.save(update_fields=["is_build_in", "team"])
    else:
        obj.save(update_fields=["is_build_in"])
    return obj


def test_get_guest_provider_adds_missing_team_and_returns_payload():
    llm = _builtin(LLMModel, "GPT-4o", team=[1])
    rerank = _builtin(RerankProvider, "bce-reranker-base_v1", team=[1])
    embed1 = _builtin(EmbedProvider, "bce-embedding-base_v1", team=[1])
    embed2 = _builtin(EmbedProvider, "FastEmbed(BAAI/bge-small-zh-v1.5)", team=[])
    paddle = _builtin(OCRProvider, "PaddleOCR", team=[1])
    azure = _builtin(OCRProvider, "AzureOCR", team=[])
    olm = _builtin(OCRProvider, "OlmOCR", team=[1])

    result = get_guest_provider(9)
    assert result["result"] is True
    data = result["data"]
    assert data["llm_model"] == {"id": llm.id, "name": "GPT-4o"}
    assert data["rerank_model"] == {"id": rerank.id, "name": "bce-reranker-base_v1"}
    assert {item["name"] for item in data["embed_model"]} == {
        "bce-embedding-base_v1",
        "FastEmbed(BAAI/bge-small-zh-v1.5)",
    }
    assert {item["name"] for item in data["ocr_model"]} == {"PaddleOCR", "AzureOCR", "OlmOCR"}

    llm.refresh_from_db()
    embed2.refresh_from_db()
    azure.refresh_from_db()
    assert 9 in llm.team
    assert 9 in embed2.team
    assert 9 in azure.team
    # 已包含的组织不会丢
    assert 1 in llm.team
