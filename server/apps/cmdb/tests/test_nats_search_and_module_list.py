"""CMDB NATS：模块列表、实例检索、organization 范围解析。"""
from unittest.mock import patch

import pytest

from apps.cmdb.constants.constants import PERMISSION_INSTANCES, PERMISSION_MODEL, PERMISSION_TASK
from apps.cmdb.nats import nats as N

pytestmark = pytest.mark.unit


def test_resolve_allowed_org_ids_explicit_and_payload_default():
    assert N._resolve_allowed_org_ids({"allowed_org_ids": [1, 2]}, {"organization": [9]}) == [1, 2]
    assert N._resolve_allowed_org_ids({}, {"organization": [3, 5]}) == [3, 5]
    assert N._resolve_allowed_org_ids({}, {"organization": 7}) is None
    assert N._resolve_allowed_org_ids({}, {}) is None


@patch("apps.cmdb.nats.nats.InstanceManage")
def test_search_instances_returns_first_or_empty(mock_im):
    mock_im.search_inst.return_value = ([{"_id": 1, "inst_name": "h1"}], 1)
    assert N.search_instances({"model_id": "host", "inst_name": "h1"}) == {"_id": 1, "inst_name": "h1"}
    mock_im.search_inst.assert_called_once_with(model_id="host", inst_name="h1", _id=None)
    mock_im.search_inst.return_value = ([], 0)
    assert N.search_instances({"model_id": "host", "_id": 9}) == {}


@patch("apps.cmdb.nats.nats.InstanceManage")
def test_search_instances_batch_forwards_ids_and_names(mock_im):
    mock_im.search_inst_batch.return_value = {"1": {"inst_name": "h1"}}
    out = N.search_instances_batch({"model_id": "host", "ids": [1], "inst_names": ["h1"]})
    assert out == {"1": {"inst_name": "h1"}}
    mock_im.search_inst_batch.assert_called_once_with(model_id="host", ids=[1], inst_names=["h1"])


@patch("apps.cmdb.nats.nats.ModelManage")
@patch("apps.cmdb.nats.nats.ClassificationManage")
def test_get_cmdb_module_list_nests_models_under_classification(mock_cm, mock_mm):
    mock_cm.search_model_classification.return_value = [
        {"classification_id": "infra", "classification_name": "基础设施"},
        {"classification_id": "empty", "classification_name": "空分类"},
    ]
    mock_mm.search_model.return_value = [
        {"classification_id": "infra", "model_id": "host", "model_name": "主机"},
        {"classification_id": "infra", "model_id": "switch", "model_name": "交换机"},
    ]
    result = N.get_cmdb_module_list()
    by_name = {item["name"]: item for item in result}
    assert set(by_name) == {PERMISSION_MODEL, PERMISSION_INSTANCES, PERMISSION_TASK}
    model_children = {c["name"] for c in by_name[PERMISSION_MODEL]["children"]}
    assert model_children == {"infra", "empty"}
    inst_children = {c["name"]: c["children"] for c in by_name[PERMISSION_INSTANCES]["children"]}
    assert {c["name"] for c in inst_children["infra"]} == {"host", "switch"}
    assert inst_children["empty"] == []
    assert by_name[PERMISSION_TASK]["children"]


@patch("apps.cmdb.nats.nats.InstanceManage")
def test_search_model_attrs_and_classifications_and_associations(mock_im):
    with patch("apps.cmdb.nats.nats.ModelManage") as mock_mm:
        mock_mm.search_model_attr.return_value = [{"attr_id": "ip"}]
        assert N.search_model_attrs({"model_id": "host"}) == [{"attr_id": "ip"}]
        mock_mm.search_model_attr.assert_called_once_with("host")
        mock_mm.search_model.return_value = [{"model_id": "host"}]
        assert N.search_models({"classification_id": "infra"}) == [{"model_id": "host"}]
        mock_mm.model_association_search.return_value = [{"asst_id": "connect"}]
        assert N.search_model_associations({"model_id": "host"}) == [{"asst_id": "connect"}]
    with pytest.raises(ValueError, match="model_id is required"):
        N.search_model_attrs({})
    with patch("apps.cmdb.nats.nats.ClassificationManage") as mock_cm:
        mock_cm.search_model_classification.return_value = [{"classification_id": "infra"}]
        assert N.search_classifications() == [{"classification_id": "infra"}]
    mock_im.instance_association_instance_list.return_value = [{"_id": 1}]
    assert N.search_instance_associations({"model_id": "host", "inst_id": 1}) == [{"_id": 1}]
    with pytest.raises(ValueError, match="model_id and inst_id"):
        N.search_instance_associations({"model_id": "host"})


def test_get_cmdb_module_data_empty_permission_and_invalid_module():
    empty = N.get_cmdb_module_data(PERMISSION_INSTANCES, "host", 1, 10, 1, user_info=None)
    assert empty == {"count": 0, "items": []}
    with pytest.raises(ValueError, match="Invalid module type"):
        N.get_cmdb_module_data("unknown", "x", 1, 10, 1)


@patch("apps.cmdb.nats.nats.ModelManage")
def test_get_cmdb_module_data_model_branch(mock_mm):
    mock_mm.search_model.return_value = [{"model_id": "host", "model_name": "主机"}]
    out = N.get_cmdb_module_data(PERMISSION_MODEL, "infra", 1, 10, 1)
    assert out["count"] == 1
    assert out["items"][0] == {"id": "host", "name": "主机"}


@patch("apps.cmdb.nats.nats.InstanceManage")
@patch("apps.cmdb.nats.nats._build_nats_permission_map", return_value={1: {}})
def test_get_cmdb_module_data_instances_uses_permission_map(mock_perm, mock_im):
    mock_im.instance_list.return_value = ([{"inst_name": "h1"}], 1)
    out = N.get_cmdb_module_data(PERMISSION_INSTANCES, "host", 1, 10, 3, user_info={"user": "u", "team": 1})
    assert out["items"][0]["id"] == "h1"
    mock_im.instance_list.assert_called_once()
    assert mock_im.instance_list.call_args.kwargs["permission_map"] == {1: {}}


@patch("apps.cmdb.nats.nats._build_nats_permission_map", return_value=None)
@patch("apps.cmdb.nats.nats._build_nats_model_permission_map", return_value=None)
def test_get_cmdb_statistics_returns_zeros_without_permission(mock_model, mock_inst):
    out = N.get_cmdb_statistics(user_info={"user": "u", "team": 1})
    assert out["result"] is True
    assert out["data"]["model_count"] == 0
    assert out["data"]["instance_count"] == 0


@patch("apps.cmdb.nats.nats.ClassificationManage")
@patch("apps.cmdb.nats.nats.ModelManage")
@patch("apps.cmdb.nats.nats.InstanceManage")
@patch("apps.cmdb.nats.nats._build_nats_permission_map", return_value={1: {}})
@patch("apps.cmdb.nats.nats._build_nats_model_permission_map", return_value={1: {}})
def test_get_cmdb_statistics_computes_coverage(mock_model_perm, mock_inst_perm, mock_im, mock_mm, mock_cm):
    mock_cm.search_model_classification.return_value = [{}, {}]
    mock_mm.search_model.return_value = [{"model_id": "host"}, {"model_id": "empty"}]
    mock_im.model_inst_count.return_value = {"host": 4, "empty": 0}
    out = N.get_cmdb_statistics(user_info={"user": "u", "team": 1})
    data = out["data"]
    assert data["model_count"] == 2
    assert data["instance_count"] == 4
    assert data["classification_count"] == 2
    assert data["model_with_instance_count"] == 1
    assert data["empty_model_count"] == 1
    assert data["model_coverage_rate"] == 50.0
