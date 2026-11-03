from collections.abc import Callable
from functools import lru_cache
from typing import Any

from .client import AsyncEmailClient


def make_get_email_client(settings: Any) -> Callable[[], AsyncEmailClient]:
    """
    The FastAPI dependency for the email client of a service, built from its settings
    (`redis_url`). One client per process (`lru_cache`), so the Celery app is made once.

    The return annotation stays: `make_service_factory` reads the type of an `extra`
    dependency from it.
    """

    @lru_cache
    def get_email_client() -> AsyncEmailClient:
        return AsyncEmailClient(broker_url=settings.redis_url)

    return get_email_client
