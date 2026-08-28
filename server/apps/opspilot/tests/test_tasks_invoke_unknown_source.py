"""invoke_one_document：未知知识来源类型直接失败。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.opspilot import tasks

pytestmark = pytest.mark.unit


def test_invoke_one_document_rejects_unknown_source():
    document = SimpleNamespace(knowledge_source_type="unknown", name="doc-881", chunk_size=0)
    with (
        patch.object(tasks, "_prepare_ingest_params", return_value={}),
        patch.object(tasks, "PgvectorRag", return_value=SimpleNamespace()),
    ):
        ok, docs, err = tasks.invoke_one_document(document)
    assert ok is False
    assert docs == []
    assert "不支持的文档类型" in err
