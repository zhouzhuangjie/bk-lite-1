"""GraphitiRAG：LLM endpoint SSRF、缺少 graph_database 拒绝建图。"""
import pytest

from apps.core.utils.ssrf_validator import SSRFError
from apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag import GraphitiRAG

pytestmark = pytest.mark.unit


@pytest.fixture
def rag(monkeypatch):
    monkeypatch.setattr(
        "apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.apply_openai_client_patch",
        lambda: None,
    )
    return GraphitiRAG()


def test_create_llm_client_blocks_cloud_metadata(rag):
    with pytest.raises(SSRFError):
        rag._create_llm_client({"api_key": "k", "model": "m", "base_url": "http://169.254.169.254/"})


def test_create_full_graphiti_requires_graph_database(rag):
    with pytest.raises(ValueError, match="graph_database"):
        rag._create_full_graphiti()
