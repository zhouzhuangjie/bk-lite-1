"""Azure OCR / 语义分块 / 图片加载 / OCR 工厂与 monitor 工具参数守卫。"""
import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.base.tests.factories import UserFactory
from apps.opspilot.metis.llm.chunk.semantic_chunk import SemanticChunk
from apps.opspilot.metis.llm.loader.image_loader import ImageLoader
from apps.opspilot.metis.ocr.azure_ocr import AzureOCR
from apps.opspilot.metis.ocr.ocr_manager import OcrManager
from apps.opspilot.models import ModelVendor
from apps.opspilot.serializers.ocr_serializer import OCRProviderSerializer

pytestmark = pytest.mark.django_db
factory = APIRequestFactory()


def test_azure_ocr_predict_concatenates_lines_and_swallows_client_error(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"png")
    page = SimpleNamespace(lines=[SimpleNamespace(text="hello"), SimpleNamespace(text="world")])
    running = SimpleNamespace(status="running")
    done = SimpleNamespace(
        status=__import__("azure.cognitiveservices.vision.computervision.models", fromlist=["OperationStatusCodes"]).OperationStatusCodes.succeeded,
        analyze_result=SimpleNamespace(read_results=[page]),
    )
    client = MagicMock()
    client.read_in_stream.return_value.headers = {"Operation-Location": "https://ocr.example/ops/abc"}
    client.get_read_result.side_effect = [running, done]
    with (
        patch("apps.opspilot.metis.ocr.azure_ocr.ComputerVisionClient", return_value=client),
        patch("apps.opspilot.metis.ocr.azure_ocr.CognitiveServicesCredentials"),
        patch("apps.opspilot.metis.ocr.azure_ocr.time.sleep") as sleep,
    ):
        assert AzureOCR("https://ocr.example", "key").predict(str(img)) == "hello world "
    sleep.assert_called_once_with(1)

    client.read_in_stream.side_effect = RuntimeError("azure down")
    with (
        patch("apps.opspilot.metis.ocr.azure_ocr.ComputerVisionClient", return_value=client),
        patch("apps.opspilot.metis.ocr.azure_ocr.CognitiveServicesCredentials"),
    ):
        assert AzureOCR("https://ocr.example", "key").predict(str(img)) == ""


def test_semantic_chunk_rejects_empty_model_and_splits_or_reraises():
    with pytest.raises(ValueError, match="semantic_embedding_model 不能为空"):
        SemanticChunk(None)

    with patch("apps.opspilot.metis.llm.chunk.semantic_chunk.SemanticChunker", side_effect=RuntimeError("init boom")):
        with pytest.raises(RuntimeError, match="init boom"):
            SemanticChunk(object())

    splitter = MagicMock()
    splitter.split_documents.return_value = [Document(page_content="chunk")]
    with patch("apps.opspilot.metis.llm.chunk.semantic_chunk.SemanticChunker", return_value=splitter):
        chunker = SemanticChunk(object())
        assert chunker._split_documents([]) == []
        docs = [Document(page_content="raw")]
        assert chunker._split_documents(docs)[0].page_content == "chunk"
        splitter.split_documents.side_effect = RuntimeError("split boom")
        with pytest.raises(RuntimeError, match="split boom"):
            chunker._split_documents(docs)


def test_image_loader_embeds_ocr_text_and_base64(tmp_path):
    path = tmp_path / "pic.bin"
    path.write_bytes(b"img-bytes")

    class _OCR:
        def predict(self, file):
            assert file == str(path)
            return "from-ocr"

    docs = ImageLoader(str(path), _OCR()).load()
    assert len(docs) == 1
    assert docs[0].page_content == "from-ocr"
    assert docs[0].metadata["format"] == "image"
    assert docs[0].metadata["image_base64"] == base64.b64encode(b"img-bytes").decode("utf-8")


def test_ocr_manager_routes_olm_azure_and_unknown():
    with (
        patch("apps.opspilot.metis.ocr.ocr_manager.OlmOcr") as olm,
        patch("apps.opspilot.metis.ocr.ocr_manager.AzureOCR") as azure,
    ):
        olm.return_value = "olm-inst"
        azure.return_value = "azure-inst"
        assert OcrManager.load_ocr("olm_ocr", model="m1", base_url="http://u", api_key="k") == "olm-inst"
        olm.assert_called_once_with(base_url="http://u", api_key="k", model="m1")
        assert OcrManager.load_ocr("azure_ocr", base_url="http://az", api_key="ak") == "azure-inst"
        azure.assert_called_once_with(azure_ocr_key="ak", azure_ocr_endpoint="http://az")
        assert OcrManager.load_ocr("unknown") is None


def _ocr_request(user):
    req = factory.post("/")
    force_authenticate(req, user=user)
    req.user = user
    req.COOKIES["current_team"] = "1"
    return req


def test_ocr_provider_serializer_requires_vendor_and_non_azure_model():
    user = UserFactory(is_superuser=True, group_list=[{"id": 1, "name": "T1"}])
    req = _ocr_request(user)
    azure = ModelVendor.objects.create(name="azure-v", vendor_type="azure", team=[1])
    openai = ModelVendor.objects.create(name="oa-v", vendor_type="openai", team=[1])
    ctx = {"request": req}

    with patch("apps.core.utils.serializers.get_permission_rules", return_value={"team": [1], "instance": []}):
        missing = OCRProviderSerializer(data={"name": "n", "team": [1], "enabled": True}, context=ctx)
        assert not missing.is_valid()
        assert missing.errors["vendor"] == ["供应商不能为空"]

        no_model = OCRProviderSerializer(
            data={"name": "n2", "team": [1], "enabled": True, "vendor": openai.id, "model": ""},
            context=ctx,
        )
        assert not no_model.is_valid()
        assert no_model.errors["model"] == ["非 Azure OCR 模型不能为空"]

        ok = OCRProviderSerializer(
            data={"name": "azure-ocr", "team": [1], "enabled": True, "vendor": azure.id, "model": ""},
            context=ctx,
        )
        assert ok.is_valid(), ok.errors
        obj = ok.save()
        assert obj.is_build_in is False
        assert obj.vendor_id == azure.id


def test_monitor_alert_and_metric_tools_guard_and_forward(mocker):
    from apps.opspilot.metis.llm.tools.monitor.alerts import monitor_list_active_alerts, monitor_query_alert_segments
    from apps.opspilot.metis.llm.tools.monitor.metrics import (
        monitor_list_instance_metrics,
        monitor_list_object_metrics,
        monitor_query_metric_data,
    )

    runtime = {"username": "alice", "password": "secret", "domain": "d.com", "team_id": 3}
    mocker.patch("apps.opspilot.metis.llm.tools.monitor.alerts.resolve_monitor_runtime_params", return_value=runtime)
    mocker.patch("apps.opspilot.metis.llm.tools.monitor.metrics.resolve_monitor_runtime_params", return_value=runtime)
    alerts_rpc = mocker.patch(
        "apps.opspilot.metis.llm.tools.monitor.alerts.call_monitor_rpc",
        return_value={"success": True, "data": []},
    )
    metrics_rpc = mocker.patch(
        "apps.opspilot.metis.llm.tools.monitor.metrics.call_monitor_rpc",
        return_value={"success": True, "data": []},
    )

    listed = monitor_list_active_alerts.invoke({"monitor_obj_id": "host", "limit": 4, "instance_ids": ["i1"]})
    assert listed == {"success": True, "data": []}
    assert alerts_rpc.call_args.args[0] == "query_latest_active_alerts"
    assert alerts_rpc.call_args.kwargs["query_data"] == {
        "monitor_obj_id": "host",
        "limit": 4,
        "instance_ids": ["i1"],
        "level": None,
        "alert_type": None,
    }

    assert monitor_query_alert_segments.invoke({})["error"] == "monitor_obj_id is required"
    assert monitor_query_alert_segments.invoke({"monitor_obj_id": "host"})["error"] == "start is required"
    assert monitor_query_alert_segments.invoke({"monitor_obj_id": "host", "start": 1})["error"] == "end is required"
    segs = monitor_query_alert_segments.invoke({"monitor_obj_id": "host", "start": 1, "end": 2, "page": 2})
    assert segs == {"success": True, "data": []}
    assert alerts_rpc.call_args.args[0] == "query_monitor_alert_segments"
    assert alerts_rpc.call_args.kwargs["query_data"]["page"] == 2

    assert monitor_list_object_metrics.invoke({"monitor_obj_id": ""})["error"] == "monitor_obj_id is required"
    assert monitor_list_object_metrics.invoke({"monitor_obj_id": "host"}) == {"success": True, "data": []}
    assert metrics_rpc.call_args.args[0] == "monitor_metrics"
    assert metrics_rpc.call_args.kwargs["monitor_obj_id"] == "host"

    assert monitor_list_instance_metrics.invoke({"monitor_obj_id": "", "instance_id": "i"})["error"] == "monitor_obj_id is required"
    assert monitor_list_instance_metrics.invoke({"monitor_obj_id": "host", "instance_id": ""})["error"] == "instance_id is required"
    inst = monitor_list_instance_metrics.invoke({"monitor_obj_id": "host", "instance_id": "i1", "page_size": 20})
    assert inst == {"success": True, "data": []}
    assert metrics_rpc.call_args.args[0] == "monitor_instance_metrics"
    assert metrics_rpc.call_args.kwargs["query_data"]["instance_id"] == "i1"

    assert monitor_query_metric_data.invoke({"monitor_obj_id": "host", "metric": "", "start": 1, "end": 2})["error"] == "metric is required"
    assert monitor_query_metric_data.invoke({"monitor_obj_id": "host", "metric": "cpu", "start": "", "end": 2})["error"] == "start is required"
    assert monitor_query_metric_data.invoke({"monitor_obj_id": "host", "metric": "cpu", "start": 1, "end": ""})["error"] == "end is required"
    queried = monitor_query_metric_data.invoke(
        {"monitor_obj_id": "host", "metric": "cpu", "start": 1, "end": 2, "step": "1m", "instance_ids": ["i1"]}
    )
    assert queried == {"success": True, "data": []}
    assert metrics_rpc.call_args.args[0] == "query_monitor_data_by_metric"
    assert metrics_rpc.call_args.kwargs["query_data"]["step"] == "1m"


def test_ocr_provider_update_validate_uses_instance_vendor():
    user = UserFactory(is_superuser=True, group_list=[{"id": 1, "name": "T1"}])
    req = _ocr_request(user)
    openai = ModelVendor.objects.create(name="oa-upd", vendor_type="openai", team=[1])
    from apps.opspilot.models import OCRProvider

    inst = OCRProvider.objects.create(name="old", team=[1], vendor=openai, model="m1")
    with patch("apps.core.utils.serializers.get_permission_rules", return_value={"team": [1], "instance": []}):
        ser = OCRProviderSerializer(inst, data={"name": "old2", "team": [1]}, partial=True, context={"request": req})
        assert ser.is_valid(), ser.errors
        ser = OCRProviderSerializer(inst, data={"model": ""}, partial=True, context={"request": req})
        assert not ser.is_valid()
        assert ser.errors["model"] == ["非 Azure OCR 模型不能为空"]
