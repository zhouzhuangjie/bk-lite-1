"""DocumentRetrieverRequest 搜索参数契约。"""
import pytest

from apps.opspilot.metis.llm.rag.naive_rag_entity import DocumentRetrieverRequest

pytestmark = pytest.mark.unit


def test_effective_fetch_k_defaults_for_mmr_and_passthrough_for_similarity():
    mmr = DocumentRetrieverRequest(index_name="kb", search_type="mmr", k=5)
    assert mmr.get_effective_fetch_k() == 20
    mmr_custom = DocumentRetrieverRequest(index_name="kb", search_type="mmr", k=5, fetch_k=30)
    assert mmr_custom.get_effective_fetch_k() == 30
    sim = DocumentRetrieverRequest(index_name="kb", search_type="similarity_score_threshold", k=7)
    assert sim.get_effective_fetch_k() == 7


def test_validate_search_params_rejects_invalid_mmr_and_missing_threshold():
    ok = DocumentRetrieverRequest(index_name="kb", search_type="mmr", k=5, fetch_k=10)
    assert ok.validate_search_params() is True

    bad_mmr = DocumentRetrieverRequest(index_name="kb", search_type="mmr", k=8, fetch_k=3)
    with pytest.raises(ValueError, match="fetch_k不能小于k"):
        bad_mmr.validate_search_params()

    missing = DocumentRetrieverRequest(index_name="kb", search_type="similarity_score_threshold")
    missing.score_threshold = None
    with pytest.raises(ValueError, match="score_threshold不能为None"):
        missing.validate_search_params()
