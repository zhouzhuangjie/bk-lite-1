import json
from pathlib import Path


VALID_GROUP_ALGORITHMS = {"avg", "max", "min", "sum", "count"}
VALID_WINDOW_ALGORITHMS = {
    "avg_over_time",
    "max_over_time",
    "min_over_time",
    "sum_over_time",
    "count_over_time",
    "last_over_time",
}


def _iter_policy_items(value, path):
    if isinstance(value, dict):
        if "algorithm" in value:
            yield path, value
        for key, item in value.items():
            yield from _iter_policy_items(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_policy_items(item, f"{path}[{index}]")


def test_policy_templates_use_supported_aggregation_methods():
    from apps.monitor.tasks.utils.policy_methods import LEGACY_ALGORITHM_MAPPING

    root = Path(__file__).resolve().parents[1] / "support-files" / "plugins"
    errors = []

    for policy_path in root.rglob("policy.json"):
        data = json.loads(policy_path.read_text())
        for item_path, item in _iter_policy_items(data, str(policy_path)):
            algorithm = item.get("algorithm")
            group_algorithm = item.get("group_algorithm")
            # 旧版 Threshold 模板不是 PromQL 两段聚合，跳过。
            if algorithm == "Threshold" or not isinstance(item.get("threshold"), list):
                continue
            if group_algorithm:
                if group_algorithm not in VALID_GROUP_ALGORITHMS:
                    errors.append(f"{item_path}: invalid group_algorithm={group_algorithm!r}")
                if algorithm not in VALID_WINDOW_ALGORITHMS:
                    errors.append(f"{item_path}: invalid algorithm={algorithm!r}")
            elif algorithm not in LEGACY_ALGORITHM_MAPPING:
                errors.append(f"{item_path}: unsupported legacy algorithm={algorithm!r}")

    assert errors == []
