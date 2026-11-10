"""The removed names stay removed: nothing in the services uses them."""

import importlib.util

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


def test_the_client_of_the_profiles_api_is_gone():
    """The applicants, agents and evaluators live in the applications-api now."""
    from atsig_common import events
    from atsig_common.api_client.factory import APIClientFactory

    assert not hasattr(APIClientFactory, "get_users_api")
    assert not hasattr(events, "ApplicantNameSync")
    assert not hasattr(events.Streams, "APPLICANT_NAMES")
    assert importlib.util.find_spec("atsig_common.api_client.clients.users_api") is None
