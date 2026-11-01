"""Shared test helpers. Tests are pure logic: no database, no network, no real Redis."""

from typing import Any

import pytest
from redis.exceptions import ResponseError


class FakeRedis:
    """
    Stand-in for RedisManager. Records every command as a tuple in `calls`, so a
    test can assert what the code under test did (and did not) send to Redis.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.groups: set[tuple[str, str]] = set()
        self.fail_xadd = False
        self.fail_xack = False

    async def xgroup_create(
        self, name: str, groupname: str, id: str = "$", mkstream: bool = False
    ) -> None:
        self.calls.append(("xgroup_create", name, groupname, id, mkstream))
        if (name, groupname) in self.groups:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self.groups.add((name, groupname))

    async def xadd(self, name: str, fields: dict[str, Any], **kwargs: Any) -> str:
        self.calls.append(("xadd", name, fields, kwargs))
        if self.fail_xadd:
            raise ConnectionError("xadd failed")
        return "1-0"

    async def xack(self, name: str, groupname: str, *ids: str) -> int:
        self.calls.append(("xack", name, groupname, *ids))
        if self.fail_xack:
            raise ConnectionError("xack failed")
        return len(ids)

    def commands(self, name: str) -> list[tuple[Any, ...]]:
        """All recorded calls of one command, in order."""
        return [call for call in self.calls if call[0] == name]


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()
