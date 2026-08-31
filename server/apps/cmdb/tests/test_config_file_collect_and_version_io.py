"""ConfigFileCollect 触发响应校验与 ConfigFileVersion 内容读写。"""
import gzip
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.cmdb.collection.collect_tasks.config_file_collect import ConfigFileCollect
from apps.cmdb.models.config_file_version import ConfigFileVersion
from apps.core.exceptions.base_app_exception import BaseAppException

pytestmark = pytest.mark.django_db


def test_parse_positive_int_and_validate_trigger_response():
    with pytest.raises(BaseAppException, match="缺少有效的 X-Task-Count"):
        ConfigFileCollect._parse_positive_int("x", "X-Task-Count")
    with pytest.raises(BaseAppException, match="必须大于 0"):
        ConfigFileCollect._parse_positive_int(0, "X-Task-Count")
    assert ConfigFileCollect._parse_positive_int("3", "X-Task-Count") == 3

    ConfigFileCollect._validate_trigger_response(SimpleNamespace(headers={"X-Task-Count": "2", "X-Success-Count": "2"}))
    with pytest.raises(BaseAppException, match="配置文件采集触发不完整"):
        ConfigFileCollect._validate_trigger_response(SimpleNamespace(headers={"X-Task-Count": "2", "X-Success-Count": "1"}))
    ConfigFileCollect._validate_trigger_response(SimpleNamespace(headers={"X-Task-Status": "queued"}))
    ConfigFileCollect._validate_trigger_response(SimpleNamespace(headers={"X-Task-Status": "skipped"}))
    with pytest.raises(BaseAppException, match="配置文件采集触发失败: unknown"):
        ConfigFileCollect._validate_trigger_response(SimpleNamespace(headers={}))


def test_trigger_remote_collection_timeout_and_http_error():
    collect = ConfigFileCollect.__new__(ConfigFileCollect)
    collect.task = SimpleNamespace(id=1, timeout=5, instances=[], params={})
    collect.file_path = "/etc/a"
    with patch.object(
        collect,
        "_build_trigger_request",
        return_value=("http://stargazer/api", {}, {}, 10),
    ), patch("apps.cmdb.collection.collect_tasks.config_file_collect.requests.get", side_effect=__import__("requests").Timeout("t")):
        with pytest.raises(BaseAppException, match="配置文件采集触发超时"):
            collect._trigger_remote_collection()

    resp = MagicMock(status_code=500, text="boom")
    with patch.object(
        collect,
        "_build_trigger_request",
        return_value=("http://stargazer/api", {}, {}, 10),
    ), patch("apps.cmdb.collection.collect_tasks.config_file_collect.requests.get", return_value=resp):
        with pytest.raises(BaseAppException, match="Stargazer 返回 500"):
            collect._trigger_remote_collection()

    with patch.object(
        collect,
        "_build_trigger_request",
        return_value=("http://stargazer/api", {}, {}, 10),
    ), patch(
        "apps.cmdb.collection.collect_tasks.config_file_collect.requests.get",
        side_effect=__import__("requests").RequestException("net"),
    ):
        with pytest.raises(BaseAppException, match="配置文件采集触发失败: net"):
            collect._trigger_remote_collection()


class _MemoryContent:
    def __init__(self, data, name="a.conf"):
        self._data = data
        self.name = name

    def __bool__(self):
        return True

    def open(self, mode="rb"):
        return BytesIO(self._data)


def test_config_file_version_gzip_and_plain_content():
    ver = ConfigFileVersion(
        instance_id="5",
        model_id="host",
        version="v1",
        file_path="/etc/a.conf",
        file_name="a.conf",
        status="success",
    )
    assert ver.read_content_bytes() == b""
    assert ver.read_content() == ""
    assert ver.content_key == ""

    ver.__dict__["content"] = _MemoryContent(gzip.compress(b"hello"), "a.conf.gz")
    assert ver.read_content_bytes() == b"hello"
    assert ver.read_content() == "hello"
    assert ver.content_key == "a.conf.gz"

    plain = ConfigFileVersion(
        instance_id="5",
        model_id="host",
        version="v2",
        file_path="/etc/b.conf",
        file_name="b.conf",
        status="success",
    )
    plain.__dict__["content"] = _MemoryContent(b"plain-text", "b.conf")
    assert plain.read_content_bytes() == b"plain-text"
    assert plain.read_content() == "plain-text"

    holder = MagicMock()
    ver.__dict__["content"] = holder
    ver.save_content("txt", "obj-key")
    holder.save.assert_called_once()
    assert holder.save.call_args.args[0] == "obj-key"
