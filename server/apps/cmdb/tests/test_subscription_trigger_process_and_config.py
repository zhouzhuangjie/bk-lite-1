"""SubscriptionTriggerService 编排 / 实例拉取 / 关联回退 / 配置文件契约。

仅 mock InstanceManage / ModelManage 图边界；ChangeRecord、ConfigFileVersion、
SubscriptionRule 走真实 DB。锁定：
- process：有实例时按 trigger_types 分发，并写回快照；
- _get_current_instances：空 instance_ids / CONDITION 分页 / INSTANCES 查询；
- _get_relation_instances：批量成功、批量失败后按实例回退；
- 非 merge 模式立即 emit；关联查询失败跳过；到期空值/非法值跳过；
- 配置文件：窗口内 SUCCESS 版本去重通知。
"""
import pydantic.root_model  # noqa

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.cmdb.constants.subscription import FilterType, TriggerType
from apps.cmdb.models.change_record import UPDATE_INST, ChangeRecord
from apps.cmdb.models.config_file_version import ConfigFileVersion, ConfigFileVersionStatus
from apps.cmdb.models.subscription_rule import SubscriptionRule
from apps.cmdb.services.subscription_trigger import (
    SubscriptionTriggerService,
    TriggerEvent,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def patch_model_info(mocker):
    mocker.patch(
        "apps.cmdb.services.subscription_trigger.ModelManage.search_model_info",
        return_value={"model_name": "主机"},
    )


def make_rule(**kw):
    defaults = dict(
        name=kw.pop("name", "rule"),
        organization=1,
        model_id="host",
        filter_type=FilterType.INSTANCES.value,
        instance_filter={"instance_ids": [1]},
        trigger_types=[],
        trigger_config={},
        recipients={},
        channel_ids=[],
        is_enabled=True,
        snapshot_data={},
    )
    defaults.update(kw)
    return SubscriptionRule.objects.create(**defaults)


def make_change_record(model_id, inst_id, before, after, created_at, type=UPDATE_INST):
    rec = ChangeRecord.objects.create(
        model_id=model_id,
        inst_id=inst_id,
        label="host",
        type=type,
        before_data=before,
        after_data=after,
    )
    ChangeRecord.objects.filter(id=rec.id).update(created_at=created_at)
    rec.refresh_from_db()
    return rec


class TestTriggerEventToDict:
    pytestmark = pytest.mark.unit

    def test_to_dict_字段完整(self):
        ev = TriggerEvent(
            rule_id=1, rule_name="r", model_id="host", model_name="主机",
            trigger_type="attribute_change", inst_id=7, inst_name="h7",
            change_summary="s", triggered_at="t",
        )
        assert ev.to_dict()["inst_id"] == 7
        assert ev.to_dict()["change_summary"] == "s"


class TestGetCurrentInstances:
    def test_实例筛选为空直接返回(self, patch_model_info):
        rule = make_rule(name="inst_empty", instance_filter={})
        svc = SubscriptionTriggerService(rule)
        assert svc._get_current_instances() == []

    def test_实例id列表查询(self, mocker, patch_model_info):
        rule = make_rule(name="inst_ids", instance_filter={"instance_ids": [11, 12]})
        mocker.patch(
            "apps.cmdb.services.subscription_trigger.InstanceManage.instance_list",
            return_value=([{"_id": 11, "inst_name": "h11"}], 1),
        )
        svc = SubscriptionTriggerService(rule)
        out = svc._get_current_instances()
        assert out == [{"_id": 11, "inst_name": "h11"}]

    def test_条件筛选分页直到取完(self, mocker, patch_model_info):
        rule = make_rule(
            name="cond_page",
            filter_type=FilterType.CONDITION.value,
            instance_filter={"query_list": [{"field": "os", "type": "str=", "value": "linux"}]},
        )
        mocker.patch(
            "apps.cmdb.services.subscription_trigger.INSTANCE_QUERY_PAGE_SIZE",
            1,
        )
        mocker.patch(
            "apps.cmdb.services.subscription_trigger.InstanceManage.instance_list",
            side_effect=[
                ([{"_id": 1}], 2),
                ([{"_id": 2}], 2),
            ],
        )
        svc = SubscriptionTriggerService(rule)
        out = svc._get_current_instances()
        assert [i["_id"] for i in out] == [1, 2]


class TestGetRelationInstances:
    def test_批量查询成功返回空失败集(self, mocker, patch_model_info):
        rule = make_rule(name="rel_batch")
        mocker.patch(
            "apps.cmdb.services.subscription_trigger.InstanceManage.instance_association_map",
            return_value={1: [10, 11]},
        )
        svc = SubscriptionTriggerService(rule)
        relation_map, failed = svc._get_relation_instances([1], "switch")
        assert relation_map == {1: [10, 11]}
        assert failed == set()

    def test_批量失败后按实例回退并记录失败(self, mocker, patch_model_info):
        rule = make_rule(name="rel_fb")
        mocker.patch(
            "apps.cmdb.services.subscription_trigger.InstanceManage.instance_association_map",
            side_effect=RuntimeError("graph timeout"),
        )
        mocker.patch(
            "apps.cmdb.services.subscription_trigger.InstanceManage.instance_association",
            side_effect=[
                [
                    {"src_model_id": "switch", "src_inst_id": 20, "dst_model_id": "host", "dst_inst_id": 1},
                    {"src_model_id": "host", "src_inst_id": 1, "dst_model_id": "switch", "dst_inst_id": 21},
                ],
                RuntimeError("inst down"),
            ],
        )
        svc = SubscriptionTriggerService(rule)
        relation_map, failed = svc._get_relation_instances([1, 2], "switch")
        assert relation_map[1] == [20, 21]
        assert failed == {2}


class TestProcessDispatch:
    def test_有实例时按触发类型分发并写快照(self, mocker, patch_model_info):
        now = timezone.now()
        rule = make_rule(
            name="proc_all",
            trigger_types=[
                TriggerType.ATTRIBUTE_CHANGE.value,
                TriggerType.RELATION_CHANGE.value,
                TriggerType.EXPIRATION.value,
                TriggerType.CONFIG_FILE.value,
            ],
            trigger_config={
                "attribute_change": {"fields": ["cpu"]},
                "relation_change": {"related_models": [{"related_model": "switch", "fields": []}]},
                "expiration": {"time_field": "expire_at", "days_before": 7},
            },
            last_check_time=now - timedelta(hours=1),
            snapshot_data={"instances": [1], "relations": {"1": {"switch": [10]}}},
        )
        expire = (timezone.localdate() + timedelta(days=2)).isoformat()
        instances = [{"_id": 1, "inst_name": "主机1", "expire_at": expire}]
        mocker.patch.object(
            SubscriptionTriggerService, "_get_current_instances", return_value=instances
        )
        mocker.patch.object(
            SubscriptionTriggerService,
            "_get_relation_instances",
            return_value=({1: [11]}, set()),
        )
        make_change_record(
            "host", 1, {"cpu": "2"}, {"cpu": "8", "inst_name": "主机1"}, now - timedelta(minutes=10)
        )
        svc = SubscriptionTriggerService(rule)
        events = svc.process()
        types = {e.trigger_type for e in events}
        assert TriggerType.ATTRIBUTE_CHANGE.value in types
        assert TriggerType.RELATION_CHANGE.value in types
        assert TriggerType.EXPIRATION.value in types
        rule.refresh_from_db()
        assert rule.last_check_time is not None
        assert 1 in rule.snapshot_data["instances"]
        assert rule.snapshot_data["relations"]["1"]["switch"] == [11]


class TestAttributeNonMergeAndEmpty:
    def test_非合并模式立即emit进出范围(self, patch_model_info):
        now = timezone.now()
        rule = make_rule(
            name="attr_nomerg",
            filter_type=FilterType.CONDITION.value,
            trigger_types=[TriggerType.ATTRIBUTE_CHANGE.value],
            trigger_config={"attribute_change": {"fields": ["cpu"]}},
            last_check_time=now - timedelta(hours=1),
            snapshot_data={"instances": [1]},
        )
        make_change_record(
            "host", 2, {"cpu": "1"}, {"cpu": "2", "inst_name": "主机2"}, now - timedelta(minutes=5)
        )
        svc = SubscriptionTriggerService(rule)
        svc.attribute_merge_mode = "per-record"
        events = svc._check_attribute_change(
            [{"_id": 2, "inst_name": "主机2"}], now
        )
        summaries = [e.change_summary for e in events]
        assert any("进入订阅范围" in s for s in summaries)
        assert any("离开订阅范围" in s for s in summaries)
        assert any("字段变化" in s for s in summaries)

    def test_候选为空直接返回(self, patch_model_info):
        rule = make_rule(
            name="attr_nocand",
            trigger_config={"attribute_change": {"fields": ["cpu"]}},
            snapshot_data={"instances": []},
        )
        svc = SubscriptionTriggerService(rule)
        assert svc._check_attribute_change([], timezone.now()) == []

    def test_窗口无记录提前返回(self, patch_model_info):
        now = timezone.now()
        rule = make_rule(
            name="attr_norec",
            trigger_config={"attribute_change": {"fields": ["cpu"]}},
            last_check_time=now - timedelta(hours=1),
            snapshot_data={"instances": [1]},
        )
        svc = SubscriptionTriggerService(rule)
        assert svc._check_attribute_change([{"_id": 1}], now) == []

    def test_未命中监听字段跳过(self, patch_model_info):
        now = timezone.now()
        rule = make_rule(
            name="attr_nomatch",
            trigger_config={"attribute_change": {"fields": ["cpu"]}},
            last_check_time=now - timedelta(hours=1),
            snapshot_data={"instances": [1]},
        )
        make_change_record("host", 1, {"mem": "8"}, {"mem": "16"}, now - timedelta(minutes=5))
        svc = SubscriptionTriggerService(rule)
        assert svc._check_attribute_change([{"_id": 1}], now) == []


class TestRelationFailedAndFieldChange:
    def test_查询失败的实例被跳过(self, mocker, patch_model_info):
        rule = make_rule(
            name="rel_failskip",
            trigger_config={
                "relation_change": {"related_models": [{"related_model": "switch", "fields": []}]}
            },
            snapshot_data={"relations": {"1": {"switch": [10]}}},
        )
        mocker.patch(
            "apps.cmdb.services.subscription_trigger.InstanceManage.instance_list",
            return_value=([], 0),
        )
        svc = SubscriptionTriggerService(rule)
        events = svc._check_relation_change(
            {"relations": {"1": {"switch": [11]}}},
            [{"_id": 1, "inst_name": "主机1"}],
            timezone.now(),
            failed_relation_instance_ids_by_model={"switch": {1}},
        )
        assert events == []

    def test_稳定关联的字段变化写入摘要(self, mocker, patch_model_info):
        now = timezone.now()
        rule = make_rule(
            name="rel_field",
            last_check_time=now - timedelta(hours=1),
            trigger_config={
                "relation_change": {
                    "related_models": [{"related_model": "switch", "fields": ["port"]}]
                }
            },
            snapshot_data={"relations": {"1": {"switch": [100]}}},
        )
        make_change_record(
            "switch", 100, {"port": "1"}, {"port": "2"}, now - timedelta(minutes=8)
        )
        mocker.patch(
            "apps.cmdb.services.subscription_trigger.InstanceManage.instance_list",
            return_value=([{"_id": 100, "inst_name": "交换机100"}], 1),
        )
        svc = SubscriptionTriggerService(rule)
        events = svc._check_relation_change(
            {"relations": {"1": {"switch": [100]}}},
            [{"_id": 1, "inst_name": "主机1"}],
            now,
        )
        assert len(events) == 1
        assert "关联实例[交换机100]属性变化" in events[0].change_summary
        assert "port" in events[0].change_summary

    def test_监听字段未变化不入图(self, patch_model_info):
        now = timezone.now()
        rule = make_rule(name="rel_nomatch", last_check_time=now - timedelta(hours=1))
        make_change_record(
            "switch", 100, {"desc": "a"}, {"desc": "b"}, now - timedelta(minutes=5)
        )
        svc = SubscriptionTriggerService(rule)
        change_map, count = svc._build_related_change_map(
            related_model="switch",
            related_instance_ids=[100],
            watch_fields={"port"},
            checkpoint=now,
        )
        assert count == 1
        assert change_map == {}

    def test_关联名称非法id跳过(self, mocker, patch_model_info):
        rule = make_rule(name="rel_badid")
        mocker.patch(
            "apps.cmdb.services.subscription_trigger.InstanceManage.instance_list",
            return_value=([{"_id": "not-int", "inst_name": "x"}, {"_id": 10, "inst_name": "ok"}], 2),
        )
        svc = SubscriptionTriggerService(rule)
        out = svc._build_related_inst_name_map("switch", {"1": {"switch": [10]}}, {})
        assert out == {10: "ok"}


class TestExpirationSkip:
    def test_空值与无法解析跳过(self, patch_model_info):
        rule = make_rule(
            name="exp_skip",
            trigger_config={"expiration": {"time_field": "expire_at", "days_before": 7}},
        )
        svc = SubscriptionTriggerService(rule)
        events = svc._check_expiration(
            [
                {"_id": 1, "expire_at": ""},
                {"_id": 2, "expire_at": "not-a-date"},
            ],
            {},
        )
        assert events == []


class TestCheckConfigFileHappy:
    def test_窗口内成功版本去重通知(self, patch_model_info):
        now = timezone.now()
        rule = make_rule(
            name="cf_ok",
            model_id="host",
            trigger_types=[TriggerType.CONFIG_FILE.value],
            last_check_time=now - timedelta(hours=1),
            snapshot_data={"config_file_notified": {"9": "old"}},
        )
        v1 = ConfigFileVersion.objects.create(
            instance_id="1",
            model_id="host",
            version="v1",
            file_path="/etc/a.conf",
            file_name="a.conf",
            status=ConfigFileVersionStatus.SUCCESS,
        )
        v2 = ConfigFileVersion.objects.create(
            instance_id="1",
            model_id="host",
            version="v2",
            file_path="/etc/a.conf",
            file_name="a.conf",
            status=ConfigFileVersionStatus.SUCCESS,
        )
        v_skip = ConfigFileVersion.objects.create(
            instance_id="9",
            model_id="host",
            version="old",
            file_path="/etc/b.conf",
            file_name="b.conf",
            status=ConfigFileVersionStatus.SUCCESS,
        )
        ConfigFileVersion.objects.filter(id__in=[v1.id, v2.id, v_skip.id]).update(
            created_at=now - timedelta(minutes=10)
        )
        svc = SubscriptionTriggerService(rule)
        snapshot = {}
        events = svc._check_config_file(
            [{"_id": 1, "inst_name": "主机1"}, {"_id": 9, "inst_name": "已通知"}],
            snapshot,
            now,
        )
        assert len(events) == 1
        assert events[0].trigger_type == TriggerType.CONFIG_FILE.value
        assert events[0].inst_id == 1
        assert events[0].change_summary == "检测到配置采集任务采集到配置文件"
        assert "1" in snapshot["config_file_notified"]
        assert "9" not in snapshot["config_file_notified"]
