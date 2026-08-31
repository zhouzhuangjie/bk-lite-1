"""JetStream 对象存储上传/下载/列举/删除契约。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.node_mgmt.utils import s3 as s3_mod

pytestmark = pytest.mark.unit


class _Jet:
    def __init__(self):
        self.connect = AsyncMock()
        self.close = AsyncMock()
        self.put = AsyncMock()
        self.get = AsyncMock(return_value=(b"bytes", "a.bin"))
        self.delete = AsyncMock()
        self.list_objects = AsyncMock(return_value=["a.bin"])

        async def _stream(path, chunk_size):
            yield b"chunk", "a.bin", 5

        self.get_streaming = _stream


@pytest.mark.asyncio
async def test_s3_upload_download_stream_delete_and_list():
    jet = _Jet()
    with patch("apps.node_mgmt.utils.s3.JetStreamService", return_value=jet):
        upload = SimpleNamespace(open=MagicMock(), file=MagicMock(seek=MagicMock()), name="pkg.tar.gz")
        await s3_mod.upload_file_to_s3(upload, "os/arch/pkg/1/pkg.tar.gz")
        upload.open.assert_called_once_with("rb")
        upload.file.seek.assert_called_once_with(0)
        jet.put.assert_awaited_once()
        assert jet.put.await_args.args[0] == "os/arch/pkg/1/pkg.tar.gz"
        assert jet.put.await_args.kwargs["description"] == "pkg.tar.gz"

        data, name = await s3_mod.download_file_by_s3("os/arch/pkg/1/pkg.tar.gz")
        assert data == b"bytes"
        assert name == "a.bin"

        chunks = [item async for item in s3_mod.stream_download_file_by_s3("os/arch/pkg/1/pkg.tar.gz", 1024)]
        assert chunks == [(b"chunk", "a.bin", 5)]

        await s3_mod.delete_s3_file("os/arch/pkg/1/pkg.tar.gz")
        jet.delete.assert_awaited_once_with("os/arch/pkg/1/pkg.tar.gz")

        listed = await s3_mod.list_s3_files()
        assert listed == ["a.bin"]
    assert jet.connect.await_count == 5
    assert jet.close.await_count == 5
