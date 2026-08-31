"""CMDB NATS：模型实例统计、缺参分组、display 同步入口、实例计数。"""
from unittest.mock import patch

import pytest

from apps.cmdb.nats import nats as N

pytestmark = pytest.mark.unit


def test_get_instance_group_by_requires_model_and_field():
    assert N.get_instance_group_by(model_id=None, field="os") == {
        "result": False,
        "data": [],
        "message": "model_id is required",
    }
    assert N.get_instance_group_by(model_id="host", field=None) == {
        "result": False,
        "data": [],
        "message": "field is required",
    }


@patch("apps.cmdb.nats.nats.InstanceManage")
@patch("apps.cmdb.nats.nats.ModelManage")
@patch("apps.cmdb.nats.nats.ClassificationManage")
@patch("apps.cmdb.nats.nats._build_nats_permission_map", return_value={"host": ["*"]})
@patch("apps.cmdb.nats.nats._build_nats_model_permission_map", return_value={"host": ["*"]})
def test_get_model_inst_statistics_sorts_by_count(mock_model_perm, mock_inst_perm, mock_cm, mock_mm, mock_im):
    mock_cm.search_model_classification.return_value = [
        {"classification_id": "infra", "classification_name": "基础设施"},
        {"classification_id": "app", "classification_name": "应用"},
    ]
    mock_mm.search_model.return_value = [
        {"model_id": "host", "model_name": "主机", "classification_id": "infra"},
        {"model_id": "app", "model_name": "应用", "classification_id": "app"},
        {"model_id": "empty", "model_name": "空", "classification_id": "missing"},
    ]
    mock_im.model_inst_count.return_value = {"host": 10, "app": 2}
    out = N.get_model_inst_statistics(user_info={"team": 1})
    assert out["result"] is True
    assert [row["model_id"] for row in out["data"]] == ["host", "app", "empty"]
    assert out["data"][0] == {"classification": "基础设施", "model": "主机", "model_id": "host", "count": 10}
    assert out["data"][2]["classification"] == "missing"
    assert out["data"][2]["count"] == 0


@patch("apps.cmdb.nats.nats._build_nats_permission_map", return_value=None)
@patch("apps.cmdb.nats.nats._build_nats_model_permission_map", return_value={"host": ["*"]})
@patch("apps.cmdb.nats.nats.ClassificationManage")
def test_get_model_inst_statistics_empty_without_instance_permission(mock_cm, mock_model_perm, mock_inst_perm):
    mock_cm.search_model_classification.return_value = []
    assert N.get_model_inst_statistics(user_info={"team": 1}) == {"result": True, "data": [], "message": ""}


@patch("apps.cmdb.nats.nats.InstanceManage")
def test_model_inst_count_wraps_manage_result(mock_im):
    mock_im.model_inst_count.return_value = {"host": 4}
    assert N.model_inst_count() == {"result": True, "message": "", "data": {"host": 4}}
    mock_im.model_inst_count.assert_called_once_with(permissions_map={}, creator="")


@patch("apps.cmdb.nats.nats.ConfigFileService")
def test_receive_config_file_result_returns_changed_flags(mock_svc):
    mock_svc.process_collect_result.return_value = {"changed": True, "task_updated": False}
    out = N.receive_config_file_result({"task_id": "t1"})
    assert out == {"result": True, "changed": True, "task_updated": False}
    mock_svc.process_collect_result.assert_called_once_with({"task_id": "t1"})


@patch("apps.cmdb.display_field.sync.sync_display_fields_for_system_mgmt", return_value={"task_id": "tid", "status": "submitted"})
def test_sync_display_fields_forwards_payload(mock_sync):
    out = N.sync_display_fields(organizations=[{"id": 1}], users=None)
    assert out == {"task_id": "tid", "status": "submitted"}
    mock_sync.assert_called_once_with(organizations=[{"id": 1}], users=[])


@patch("apps.cmdb.nats.nats.InstanceManage")
@patch("apps.cmdb.nats.nats.ModelManage")
@patch("apps.cmdb.nats.nats._build_nats_permission_map", return_value=None)
def test_get_instance_group_by_empty_without_permission(mock_perm, mock_mm, mock_im):
    assert N.get_instance_group_by(model_id="host", field="os", user_info={"team": 1}) == {
        "result": True,
        "data": [],
        "message": "",
    }
    mock_mm.search_model_attr.assert_not_called()
    mock_im.group_inst_count.assert_not_called()


@patch("apps.cmdb.nats.nats.InstanceManage")
@patch("apps.cmdb.nats.nats.ModelManage")
@patch("apps.cmdb.nats.nats._build_nats_permission_map", return_value={"host": ["*"]})
def test_get_instance_group_by_uses_display_suffix_and_sorts(mock_perm, mock_mm, mock_im):
    mock_mm.search_model_attr.return_value = [{"attr_id": "organization", "attr_type": "organization"}]
    mock_im.group_inst_count.return_value = {"运维": 2, "研发": 5}
    out = N.get_instance_group_by(model_id="host", field="organization", user_info={"team": 1})
    assert out["result"] is True
    assert out["data"] == [{"name": "研发", "value": 5}, {"name": "运维", "value": 2}]
    mock_im.group_inst_count.assert_called_once_with(
        group_by_attr="organization_display",
        permissions_map={"host": ["*"]},
        params=[{"field": "model_id", "type": "str=", "value": "host"}],
    )


@patch("apps.cmdb.nats.nats.InstanceManage")
@patch("apps.cmdb.nats.nats.ModelManage")
@patch("apps.cmdb.nats.nats._build_nats_permission_map", return_value={"host": ["*"]})
def test_get_instance_group_by_enum_maps_unknown_and_option_name(mock_perm, mock_mm, mock_im):
    mock_mm.search_model_attr.return_value = [
        {
            "attr_id": "os_type",
            "attr_type": "enum",
            "enum_select_mode": "single",
            "option": [{"id": "linux", "name": "Linux"}, {"id": "win", "name": "Windows"}],
        }
    ]
    mock_im.group_inst_count.return_value = {"linux": 8, "": 1, "other": 3}
    out = N.get_instance_group_by(model_id="host", field="os_type", user_info={"team": 1})
    assert out["data"] == [
        {"name": "Linux", "value": 8},
        {"name": "other", "value": 3},
        {"name": "unknown", "value": 1},
    ]
    mock_im.group_inst_count.assert_called_once_with(
        group_by_attr="os_type",
        permissions_map={"host": ["*"]},
        params=[{"field": "model_id", "type": "str=", "value": "host"}],
    )
