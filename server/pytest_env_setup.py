"""Early pytest plugin to configure environment before Django setup.

Registered as a pytest11 entry point in pyproject.toml so it loads before
pytest-django calls django.setup(). Supplies dummy MinIO settings and skips
bucket initialization so tests do not need a live object store.
"""
import os

import django.core.management as mgmt

os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "test-access-key")
os.environ.setdefault("MINIO_SECRET_KEY", "test-secret-key")
os.environ.setdefault("MINIO_USE_HTTPS", "false")
os.environ.setdefault("ENABLE_CELERY", "True")

_original_call_command = mgmt.call_command


def _noop_initialize_buckets(name, *args, **kwargs):
    if name == "initialize_buckets":
        return
    return _original_call_command(name, *args, **kwargs)


# Import-time patch: must run before django.setup() initializes MinIO buckets.
mgmt.call_command = _noop_initialize_buckets
