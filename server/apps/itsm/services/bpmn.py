# flake8: noqa: E501
from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape, quoteattr

from apps.itsm.services.validation import validate_workflow_config

APPROVAL_UNIT_BPMN = b"""<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:flowable="http://flowable.org/bpmn" targetNamespace="bklite.itsm">
  <process id="itsm_approval_unit" name="ITSM approval unit" isExecutable="true">
    <startEvent id="start"><extensionElements>
      <flowable:executionListener event="start" expression="${execution.setVariable('approved', true)}"/>
      <flowable:executionListener event="start" expression="${execution.setVariable('childApproved', true)}"/>
    </extensionElements></startEvent>
    <userTask id="review" name="Approval ${who}" flowable:assignee="${who}"/>
    <exclusiveGateway id="decision"/>
    <exclusiveGateway id="preResult"/>
    <exclusiveGateway id="postResult"/>
    <callActivity id="pre" calledElement="itsm_approval_unit" flowable:sameDeployment="true"><extensionElements>
      <flowable:in sourceExpression="${person.asText()}" target="who"/>
      <flowable:in sourceExpression="${depth + 1}" target="depth"/>
      <flowable:in source="stageKey" target="stageKey"/>
      <flowable:in source="allowBeforeSign" target="allowBeforeSign"/>
      <flowable:in source="allowAfterSign" target="allowAfterSign"/>
      <flowable:out source="approved" target="childApproved"/>
    </extensionElements><multiInstanceLoopCharacteristics isSequential="false" flowable:collection="signUsers" flowable:elementVariable="person"><completionCondition>${childApproved == false}</completionCondition></multiInstanceLoopCharacteristics></callActivity>
    <callActivity id="post" calledElement="itsm_approval_unit" flowable:sameDeployment="true"><extensionElements>
      <flowable:in sourceExpression="${person.asText()}" target="who"/>
      <flowable:in sourceExpression="${depth + 1}" target="depth"/>
      <flowable:in source="stageKey" target="stageKey"/>
      <flowable:in source="allowBeforeSign" target="allowBeforeSign"/>
      <flowable:in source="allowAfterSign" target="allowAfterSign"/>
      <flowable:out source="approved" target="childApproved"/>
    </extensionElements><multiInstanceLoopCharacteristics isSequential="false" flowable:collection="postUsers" flowable:elementVariable="person"><completionCondition>${childApproved == false}</completionCondition></multiInstanceLoopCharacteristics></callActivity>
    <endEvent id="accepted"><extensionElements><flowable:executionListener event="start" expression="${execution.setVariable('approved', true)}"/></extensionElements></endEvent>
    <endEvent id="rejected"><extensionElements><flowable:executionListener event="start" expression="${execution.setVariable('approved', false)}"/></extensionElements></endEvent>
    <endEvent id="cancelled"><extensionElements><flowable:executionListener event="start" expression="${execution.setVariable('approved', true)}"/></extensionElements></endEvent>
    <sequenceFlow id="start_review" sourceRef="start" targetRef="review"/>
    <sequenceFlow id="review_decision" sourceRef="review" targetRef="decision"/>
    <sequenceFlow id="decision_pre" sourceRef="decision" targetRef="pre"><conditionExpression xsi:type="tFormalExpression"><![CDATA[${intent == 'before'}]]></conditionExpression></sequenceFlow>
    <sequenceFlow id="decision_cancelled" sourceRef="decision" targetRef="cancelled"><conditionExpression xsi:type="tFormalExpression"><![CDATA[${intent == 'cancel'}]]></conditionExpression></sequenceFlow>
    <sequenceFlow id="decision_rejected" sourceRef="decision" targetRef="rejected"><conditionExpression xsi:type="tFormalExpression"><![CDATA[${intent == 'complete' && !vote}]]></conditionExpression></sequenceFlow>
    <sequenceFlow id="decision_accepted" sourceRef="decision" targetRef="accepted"><conditionExpression xsi:type="tFormalExpression"><![CDATA[${intent == 'complete' && vote && !hasPost}]]></conditionExpression></sequenceFlow>
    <sequenceFlow id="decision_post" sourceRef="decision" targetRef="post"><conditionExpression xsi:type="tFormalExpression"><![CDATA[${intent == 'complete' && vote && hasPost}]]></conditionExpression></sequenceFlow>
    <sequenceFlow id="pre_result" sourceRef="pre" targetRef="preResult"/>
    <sequenceFlow id="pre_again" sourceRef="preResult" targetRef="review"><conditionExpression xsi:type="tFormalExpression"><![CDATA[${childApproved}]]></conditionExpression></sequenceFlow>
    <sequenceFlow id="pre_rejected" sourceRef="preResult" targetRef="rejected"><conditionExpression xsi:type="tFormalExpression"><![CDATA[${!childApproved}]]></conditionExpression></sequenceFlow>
    <sequenceFlow id="post_result" sourceRef="post" targetRef="postResult"/>
    <sequenceFlow id="post_accepted" sourceRef="postResult" targetRef="accepted"><conditionExpression xsi:type="tFormalExpression"><![CDATA[${childApproved}]]></conditionExpression></sequenceFlow>
    <sequenceFlow id="post_rejected" sourceRef="postResult" targetRef="rejected"><conditionExpression xsi:type="tFormalExpression"><![CDATA[${!childApproved}]]></conditionExpression></sequenceFlow>
  </process>
</definitions>
"""


def compile_root_bpmn(*, process_key: str, process_name: str, workflow_config: dict) -> bytes:
    validate_workflow_config(workflow_config)
    stages = workflow_config["stages"]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:flowable="http://flowable.org/bpmn" '
        'targetNamespace="bklite.itsm">',
        f'  <process id={quoteattr(process_key)} name={quoteattr(process_name)} isExecutable="true">',
        '    <startEvent id="start"/>',
    ]

    for stage in stages:
        stage_key = stage["key"]
        collection = f"approval_{stage_key}"
        sequential = "true" if stage["mode"] == "serial" else "false"
        lines.extend(
            [
                f'    <callActivity id="approval_{stage_key}" name={quoteattr(stage["name"])} calledElement="itsm_approval_unit" flowable:sameDeployment="true">',
                "      <extensionElements>",
                '        <flowable:in sourceExpression="${person.asText()}" target="who"/>',
                '        <flowable:in sourceExpression="${0}" target="depth"/>',
                f'        <flowable:in sourceExpression="${{\'{stage_key}\'}}" target="stageKey"/>',
                f'        <flowable:in sourceExpression="${{{str(stage.get("allowBeforeSign", False)).lower()}}}" target="allowBeforeSign"/>',
                f'        <flowable:in sourceExpression="${{{str(stage.get("allowAfterSign", False)).lower()}}}" target="allowAfterSign"/>',
                '        <flowable:out source="approved" target="approved"/>',
                "      </extensionElements>",
                f'      <multiInstanceLoopCharacteristics isSequential="{sequential}" flowable:collection="{collection}" flowable:elementVariable="person">',
                "        <completionCondition>${approved == false}</completionCondition>",
                "      </multiInstanceLoopCharacteristics>",
                "    </callActivity>",
                f'    <exclusiveGateway id="result_{stage_key}"/>',
            ]
        )

    lines.extend(
        [
            '    <userTask id="handle" name="Handle ticket" flowable:assignee="${handlerId}"/>',
            '    <endEvent id="completed"/>',
            '    <endEvent id="rejected"/>',
            f'    <sequenceFlow id="start_first" sourceRef="start" targetRef="approval_{stages[0]["key"]}"/>',
        ]
    )
    for index, stage in enumerate(stages):
        stage_key = stage["key"]
        next_target = f'approval_{stages[index + 1]["key"]}' if index + 1 < len(stages) else "handle"
        lines.extend(
            [
                f'    <sequenceFlow id="{stage_key}_result" sourceRef="approval_{stage_key}" targetRef="result_{stage_key}"/>',
                f'    <sequenceFlow id="{stage_key}_approved" sourceRef="result_{stage_key}" targetRef="{next_target}"><conditionExpression xsi:type="tFormalExpression"><![CDATA[${{approved}}]]></conditionExpression></sequenceFlow>',
                f'    <sequenceFlow id="{stage_key}_rejected" sourceRef="result_{stage_key}" targetRef="rejected"><conditionExpression xsi:type="tFormalExpression"><![CDATA[${{!approved}}]]></conditionExpression></sequenceFlow>',
            ]
        )
    lines.extend(['    <sequenceFlow id="handled" sourceRef="handle" targetRef="completed"/>', "  </process>", "</definitions>"])
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_reproducible(bundle: zipfile.ZipFile, filename: str, content: bytes) -> None:
    info = zipfile.ZipInfo(filename, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    bundle.writestr(info, content)


def build_deployment_archive(*, process_key: str, process_name: str, workflow_config: dict) -> bytes:
    root = compile_root_bpmn(process_key=process_key, process_name=process_name, workflow_config=workflow_config)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        _write_reproducible(bundle, "approval-unit.bpmn20.xml", APPROVAL_UNIT_BPMN)
        _write_reproducible(bundle, f"{escape(process_key)}.bpmn20.xml", root)
    return output.getvalue()
