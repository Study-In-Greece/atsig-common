from collections.abc import Callable
from functools import lru_cache
from typing import Any

from .manager import RedisManager
from .producer import EventProducer


def make_get_event_producer(
    redis_manager: RedisManager, **producer_options: Any
) -> Callable[[], EventProducer]:
    """
    The FastAPI dependency for the event producer of a service. One producer per
    process (`lru_cache`). `producer_options` go to `EventProducer` (`default_maxlen`,
    `default_retries`).

    The return annotation stays: `make_service_factory` reads the type of an `extra`
    dependency from it.
    """

    @lru_cache
    def get_event_producer() -> EventProducer:
        return EventProducer(redis_manager=redis_manager, **producer_options)

    return get_event_producer
