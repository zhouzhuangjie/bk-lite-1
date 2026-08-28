"""opspilot.tasks._run_in_native_thread：同步执行与 ORM 异步回退。"""
from unittest.mock import patch

import pytest
from django.core.exceptions import SynchronousOnlyOperation

from apps.opspilot.tasks import _run_in_native_thread

pytestmark = pytest.mark.unit


def test_run_in_native_thread_returns_callable_result():
    assert _run_in_native_thread(lambda x, y=1: x + y, 2, y=3) == 5


def test_run_in_native_thread_falls_back_when_sync_only():
    class FakeExecutor:
        def __init__(self, max_workers=1):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, fn, allow_async_unsafe):
            class Future:
                def result(self_inner):
                    if not allow_async_unsafe:
                        raise SynchronousOnlyOperation("blocked")
                    return fn(allow_async_unsafe)

            return Future()

    with (
        patch("apps.opspilot.tasks.concurrent.futures.ThreadPoolExecutor", FakeExecutor),
        patch("apps.opspilot.tasks.close_old_connections"),
    ):
        assert _run_in_native_thread(lambda: 42) == 42
