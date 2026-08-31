"""GitHub commits 工具：URL/日期校验、数据处理与请求错误映射。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from apps.opspilot.metis.llm.tools.github import commits as gh

pytestmark = pytest.mark.unit


def test_validate_github_url_and_datetime():
    assert gh._validate_github_url("https://api.github.com/repos/a/b/commits") is True
    with pytest.raises(ValueError, match="GitHub API仅支持HTTPS协议"):
        gh._validate_github_url("http://api.github.com/repos/a/b")
    with pytest.raises(ValueError, match="仅支持GitHub官方API域名"):
        gh._validate_github_url("https://evil.example/repos/a/b")
    assert gh._validate_datetime_format("2025-09-08T00:00:00Z") is True
    with pytest.raises(ValueError, match="日期格式错误"):
        gh._validate_datetime_format("not-a-date")


def test_process_commits_data_empty_and_malformed():
    assert gh._process_commits_data([]) == {}
    grouped = gh._process_commits_data(
        [
            {"commit": {"author": {"name": "alice", "date": "2025-01-02T00:00:00Z"}, "message": "b"}},
            {"commit": {"author": {"name": "alice", "date": "2025-01-03T00:00:00Z"}, "message": "c"}},
            {"commit": None},
        ]
    )
    assert list(grouped) == ["alice"]
    assert [item["message"] for item in grouped["alice"]] == ["c", "b"]


def test_fetch_github_commits_status_and_network_errors():
    fetch = gh._fetch_github_commits.__wrapped__
    url = "https://api.github.com/repos/a/b/commits"
    with patch("apps.opspilot.metis.llm.tools.github.commits.requests.get") as get:
        get.return_value = SimpleNamespace(status_code=401, json=lambda: [], text="")
        with pytest.raises(ValueError, match="GitHub API认证失败"):
            fetch(url, {})
        get.return_value = SimpleNamespace(status_code=403, json=lambda: [], text="")
        with pytest.raises(ValueError, match="访问被拒绝"):
            fetch(url, {})
        get.return_value = SimpleNamespace(status_code=404, json=lambda: [], text="")
        with pytest.raises(ValueError, match="仓库不存在"):
            fetch(url, {})
        get.return_value = SimpleNamespace(status_code=500, json=lambda: [], text="oops")
        with pytest.raises(ValueError, match="状态码: 500"):
            fetch(url, {})
        get.return_value = SimpleNamespace(status_code=200, json=lambda: [{"sha": "1"}], text="")
        assert fetch(url, {"Accept": "x"}) == [{"sha": "1"}]

        get.side_effect = requests.exceptions.Timeout()
        with pytest.raises(ValueError, match="请求超时"):
            fetch(url, {})
        get.side_effect = requests.exceptions.ConnectionError("down")
        with pytest.raises(ValueError, match="连接失败"):
            fetch(url, {})
