"""监控策略迁移：空文件跳过、导入成功、单文件失败计数。"""
import pytest

from apps.monitor.management.services import policy_migrate

pytestmark = pytest.mark.unit


def test_migrate_policy_skips_empty_imports_and_counts_errors(tmp_path, mocker):
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text('{"name": "p1"}', encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")

    mocker.patch(
        "apps.monitor.management.services.policy_migrate.find_files_by_pattern",
        side_effect=[[str(empty), str(good)], [str(bad)]],
    )
    imported = mocker.patch(
        "apps.monitor.management.services.policy_migrate.PolicyService.import_monitor_policy"
    )
    logger = mocker.patch("apps.monitor.management.services.policy_migrate.logger")

    policy_migrate.migrate_policy()

    imported.assert_called_once_with({"name": "p1"})
    messages = [call.args[0] for call in logger.info.call_args_list]
    assert any("跳过空策略配置" in msg for msg in messages)
    assert any("导入策略成功" in msg for msg in messages)
    assert any("成功=1, 失败=1" in msg for msg in messages)
    logger.error.assert_called_once()
    assert "导入策略失败" in logger.error.call_args.args[0]
