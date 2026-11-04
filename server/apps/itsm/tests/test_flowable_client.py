import io
import json
import zipfile

import httpx
import pytest

from apps.itsm.services.bpmn import build_deployment_archive, compile_root_bpmn
from apps.itsm.services.flowable import FlowableClient, FlowableConfigurationError, FlowableRejected, variable


def workflow_config():
    return {
        "schemaVersion": 1,
        "stages": [
            {
                "key": "manager",
                "name": "主管审批",
                "mode": "serial",
                "approverIds": [11, 12],
                "allowBeforeSign": True,
                "allowAfterSign": False,
            },
            {
                "key": "security",
                "name": "安全会签",
                "mode": "parallel",
                "approverIds": [21, 22],
                "allowBeforeSign": False,
                "allowAfterSign": True,
            },
        ],
        "handlerIds": [31],
    }


@pytest.mark.unit
def test_compile_root_bpmn_contains_ordered_stages_and_handler():
    xml = compile_root_bpmn(process_key="itsm_service_3_v2", process_name="数据库申请 v2", workflow_config=workflow_config())
    text = xml.decode()

    assert 'id="approval_manager"' in text
    assert 'isSequential="true"' in text
    assert 'id="approval_security"' in text
    assert 'isSequential="false"' in text
    assert text.index('id="approval_manager"') < text.index('id="approval_security"')
    assert 'flowable:assignee="${handlerId}"' in text
    assert "scriptTask" not in text


@pytest.mark.unit
def test_deployment_archive_contains_root_and_approval_unit():
    archive = build_deployment_archive(
        process_key="itsm_service_3_v2",
        process_name="数据库申请 v2",
        workflow_config=workflow_config(),
    )

    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert sorted(bundle.namelist()) == ["approval-unit.bpmn20.xml", "itsm_service_3_v2.bpmn20.xml"]
        assert b"itsm_service_3_v2" in bundle.read("itsm_service_3_v2.bpmn20.xml")


@pytest.mark.unit
def test_flowable_client_rejects_credentials_in_url():
    with pytest.raises(FlowableConfigurationError):
        FlowableClient(base_url="http://admin:secret@flowable:8080/flowable-rest/service")


@pytest.mark.unit
def test_flowable_client_deploys_archive_and_resolves_process_definition():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        if request.url.path.endswith("/repository/deployments"):
            assert request.method == "POST"
            assert "multipart/form-data" in request.headers["content-type"]
            return httpx.Response(201, json={"id": "deployment-1"})
        if request.url.path.endswith("/repository/process-definitions"):
            assert request.url.params["deploymentId"] == "deployment-1"
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "itsm_service_3_v2:1:99", "key": "itsm_service_3_v2"}],
                    "total": 1,
                    "start": 0,
                    "size": 100,
                },
            )
        raise AssertionError(request.url)

    client = FlowableClient(
        base_url="http://flowable:8080/flowable-rest/service",
        username="rest-user",
        password="rest-pass",
        transport=httpx.MockTransport(handler),
    )
    deployment = client.deploy_archive("itsm service 3 v2", b"zip-bytes", process_key="itsm_service_3_v2")

    assert deployment == {"deployment_id": "deployment-1", "process_definition_id": "itsm_service_3_v2:1:99"}
    assert len(calls) == 2
    client.close()


@pytest.mark.unit
def test_flowable_client_maps_clear_4xx_to_rejected_without_exposing_body():
    transport = httpx.MockTransport(lambda request: httpx.Response(400, json={"password": "must-not-leak"}))
    client = FlowableClient(
        base_url="http://flowable:8080/flowable-rest/service",
        username="rest-user",
        password="rest-pass",
        transport=transport,
    )

    with pytest.raises(FlowableRejected, match="明确拒绝") as captured:
        client.start_process("definition-1", business_key="ticket-1", variables=[variable("handlerId", "31")])

    assert "must-not-leak" not in str(captured.value)
    client.close()


@pytest.mark.unit
def test_variable_preserves_json_lists_for_flowable():
    encoded = variable("approval_manager", ["11", "12"])

    assert encoded == {"name": "approval_manager", "value": ["11", "12"], "type": "json"}
    assert json.dumps(encoded)


@pytest.mark.unit
def test_historic_receipt_queries_unique_command_variable():
    def handler(request: httpx.Request):
        assert request.url.path.endswith("/history/historic-variable-instances")
        assert request.url.params["variableName"] == "itsmReceipt_abc123"
        return httpx.Response(
            200,
            json={
                "data": [{"variable": {"name": "itsmReceipt_abc123", "value": "receipt-value"}}],
                "total": 1,
                "start": 0,
                "size": 100,
            },
        )

    client = FlowableClient(
        base_url="http://flowable:8080/flowable-rest/service",
        username="rest-user",
        password="rest-pass",
        transport=httpx.MockTransport(handler),
    )

    assert client.historic_receipt("itsmReceipt_abc123") == "receipt-value"
    client.close()
