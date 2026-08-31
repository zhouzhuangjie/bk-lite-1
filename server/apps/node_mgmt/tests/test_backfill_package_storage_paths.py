"""回填包对象路径命令：dry-run / apply / 过滤与 JetStream 复制契约。"""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from django.core.management import call_command
from nats.js.errors import ObjectNotFoundError

from apps.node_mgmt.management.commands.backfill_package_storage_paths import Command
from apps.node_mgmt.models.package import PackageVersion
from apps.node_mgmt.services.package import PackageService

pytestmark = pytest.mark.django_db


def _pkg(**over):
    data = dict(
        type="collector", os="linux", cpu_architecture="x86_64",
        object="telegraf", version="1.2.3", name="telegraf-1.2.3.tar.gz",
    )
    data.update(over)
    return PackageVersion.objects.create(**data)


class _FakeStore:
    def __init__(self, primary=False, legacy=False, description="legacy"):
        self.primary_exists = primary
        self.legacy_exists = legacy
        self.description = description
        self.put_calls = []

    async def get_info(self, path):
        if "generic" in path or path.count("/") == 4:
            # primary: os/arch/object/version/name
            exists = self.primary_exists if path.count("/") >= 4 and "/x86_64/" in path else self.legacy_exists
            # 更稳妥：按 PackageService 路径判断
            raise AssertionError("use command-level mocks instead")

    async def get(self, path):
        raise ObjectNotFoundError()


def test_inspect_paths_reports_primary_and_legacy_existence():
    pkg = _pkg()
    primary = PackageService.build_file_path(pkg)
    legacy = PackageService.build_legacy_file_path(pkg)
    seen = []

    class Store:
        async def get_info(self, path):
            seen.append(path)
            if path == primary:
                return SimpleNamespace()
            raise ObjectNotFoundError()

    js = SimpleNamespace(object_store=Store(), closed=False)
    js.connect = AsyncMock()
    js.close = AsyncMock()

    async def _run():
        return await Command._inspect_paths(pkg)

    import asyncio

    with patch("apps.node_mgmt.management.commands.backfill_package_storage_paths.JetStreamService", return_value=js):
        primary_exists, legacy_exists, p, l = asyncio.run(_run())

    assert primary_exists is True
    assert legacy_exists is False
    assert p == primary
    assert l == legacy
    js.close.assert_awaited()


def test_copy_legacy_to_primary_skips_when_primary_exists():
    pkg = _pkg(version="2.0.0", name="telegraf-2.0.0.tar.gz")
    primary = PackageService.build_file_path(pkg)

    class Store:
        async def get_info(self, path):
            if path == primary:
                return SimpleNamespace()
            raise ObjectNotFoundError()

        async def get(self, path):
            raise AssertionError("should not get legacy")

    js = SimpleNamespace(object_store=Store())
    js.connect = AsyncMock()
    js.close = AsyncMock()
    js.put = AsyncMock()

    import asyncio
    with patch("apps.node_mgmt.management.commands.backfill_package_storage_paths.JetStreamService", return_value=js):
        status, p, l = asyncio.run(Command._copy_legacy_to_primary(pkg))
    assert status == "primary_exists"
    js.put.assert_not_called()


def test_copy_legacy_to_primary_copies_missing_primary():
    pkg = _pkg(version="3.0.0", name="telegraf-3.0.0.tar.gz")
    primary = PackageService.build_file_path(pkg)
    legacy = PackageService.build_legacy_file_path(pkg)
    put_calls = []

    class Store:
        async def get_info(self, path):
            raise ObjectNotFoundError()

        async def get(self, path):
            assert path == legacy
            return SimpleNamespace(data=b"pkg-bytes", info=SimpleNamespace(description="desc"))

    js = SimpleNamespace(object_store=Store())
    js.connect = AsyncMock()
    js.close = AsyncMock()

    async def fake_put(path, data, description=None):
        put_calls.append((path, data, description))

    js.put = fake_put

    import asyncio
    with patch("apps.node_mgmt.management.commands.backfill_package_storage_paths.JetStreamService", return_value=js):
        status, p, l = asyncio.run(Command._copy_legacy_to_primary(pkg))
    assert status == "copied"
    assert p == primary
    assert put_calls == [(primary, b"pkg-bytes", "desc")]


def test_handle_dry_run_and_filters(monkeypatch):
    ok = _pkg(object="telegraf", version="9.0.0", name="telegraf-9.0.0.tar.gz")
    missing = _pkg(object="vector", version="9.0.0", name="vector-9.0.0.tar.gz")
    copyable = _pkg(object="telegraf", version="9.1.0", name="telegraf-9.1.0.tar.gz")

    def fake_inspect(package_obj):
        if package_obj.id == ok.id:
            return True, True, "p-ok", "l-ok"
        if package_obj.id == missing.id:
            return False, False, "p-miss", "l-miss"
        return False, True, "p-copy", "l-copy"

    def fake_async_to_sync(fn):
        name = getattr(fn, "__name__", "")
        if name == "_inspect_paths":
            return fake_inspect
        if name == "_copy_legacy_to_primary":
            return lambda obj: ("copied", "p", "l")
        raise AssertionError(name)

    monkeypatch.setattr(
        "apps.node_mgmt.management.commands.backfill_package_storage_paths.async_to_sync",
        fake_async_to_sync,
    )

    out = StringIO()
    call_command(
        "backfill_package_storage_paths",
        "--object", "telegraf",
        "--os", "linux",
        "--type", "collector",
        "--package-version", "9.1.0",
        stdout=out,
    )
    text = out.getvalue()
    assert "[dry-run]" in text
    assert "copy l-copy -> p-copy" in text
    assert "[missing]" not in text
    assert "copied=0" in text
    assert "missing=0" in text


def test_handle_apply_copies_and_counts(monkeypatch):
    pkg = _pkg(object="nats", version="1.0.1", name="nats-1.0.1.tar.gz")

    def fake_async_to_sync(fn):
        name = getattr(fn, "__name__", "")
        if name == "_inspect_paths":
            return lambda obj: (False, True, "p1", "l1")
        if name == "_copy_legacy_to_primary":
            return lambda obj: ("copied", "p1", "l1")
        raise AssertionError(name)

    monkeypatch.setattr(
        "apps.node_mgmt.management.commands.backfill_package_storage_paths.async_to_sync",
        fake_async_to_sync,
    )
    out = StringIO()
    call_command("backfill_package_storage_paths", "--apply", "--object", "nats", stdout=out)
    text = out.getvalue()
    assert f"[copied] {pkg.id}: l1 -> p1" in text
    assert "copied=1" in text


def test_handle_already_ok_and_missing(monkeypatch):
    ok = _pkg(object="okpkg", version="1.0.0", name="okpkg-1.0.0.tar.gz")
    miss = _pkg(object="misspkg", version="1.0.0", name="misspkg-1.0.0.tar.gz")

    def fake_async_to_sync(fn):
        def inspect(obj):
            if obj.id == ok.id:
                return True, False, f"p-{obj.id}", f"l-{obj.id}"
            return False, False, f"p-{obj.id}", f"l-{obj.id}"

        if getattr(fn, "__name__", "") == "_inspect_paths":
            return inspect
        raise AssertionError("copy should not run")

    monkeypatch.setattr(
        "apps.node_mgmt.management.commands.backfill_package_storage_paths.async_to_sync",
        fake_async_to_sync,
    )
    out = StringIO()
    call_command("backfill_package_storage_paths", "--apply", stdout=out)
    text = out.getvalue()
    assert f"[ok] {ok.id}:" in text
    assert f"[missing] {miss.id}:" in text
    assert "already_ok=1" in text
    assert "missing=1" in text
    assert "copied=0" in text
