"""Django settings overlay for the local interactive ITSM demo only."""

from settings import *  # noqa: F403


ROOT_URLCONF = "demo_urls"
ALLOWED_HOSTS = ["*"]

MIDDLEWARE = tuple(  # noqa: F405
    item
    for item in MIDDLEWARE  # noqa: F405
    if item != "apps.core.middlewares.auth_middleware.AuthMiddleware"
)
MIDDLEWARE += ("demo_urls.DemoAuthMiddleware",)
