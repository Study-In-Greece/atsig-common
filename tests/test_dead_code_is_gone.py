"""The removed names stay removed: nothing in the services uses them."""

from atsig_common.db import mixins
from atsig_common.redis.manager import RedisManager


def test_the_mixins_that_the_services_use_are_still_there():
    assert hasattr(mixins, "IDMixin")
    assert hasattr(mixins, "TimestampMixin")


def test_the_unused_declarative_base_is_gone():
    assert not hasattr(mixins, "Base")


def test_the_redis_manager_has_no_unused_singleton_attributes():
    assert not hasattr(RedisManager, "_instance")
    assert not hasattr(RedisManager, "_lock")
