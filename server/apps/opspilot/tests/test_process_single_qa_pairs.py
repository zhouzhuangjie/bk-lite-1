"""_process_single_qa_pairs：跳过空 instruction，失败项延迟重试后计入成功。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.tasks import _process_single_qa_pairs

pytestmark = pytest.mark.unit


def test_process_single_qa_pairs_skips_empty_and_retries_failure():
    qa_pairs = MagicMock(id=11, name="qa-set")
    task_obj = MagicMock()
    rag = MagicMock()
    rag.custom_content_ingest.side_effect = [
        {"status": "success"},
        {"status": "fail", "message": "busy"},
        {"status": "success"},
    ]
    qa_json = [
        {"instruction": "q1", "output": "a1"},
        {"instruction": "", "output": ""},
        {"instruction": "q2", "output": "a2"},
    ]
    with patch("apps.opspilot.tasks.tqdm", side_effect=lambda it: it), patch(
        "apps.opspilot.tasks.time.sleep"
    ) as slept, patch("apps.opspilot.tasks.QA_INGEST_RETRY_DELAY", 0):
        success = _process_single_qa_pairs(qa_pairs, qa_json, {"index_name": "idx"}, rag, task_obj)
    assert success == 2
    qa_pairs.save.assert_called()
    assert qa_pairs.status == "generating"
    assert task_obj.total_count == 3
    slept.assert_called_once()
    assert rag.custom_content_ingest.call_count == 3
