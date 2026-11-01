"""Shared test helpers. Tests are pure logic: no database, no network, no real Redis."""

import asyncio
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
        # What xreadgroup returns, one item per call: a response, None (nothing new)
        # or an exception to raise. When the script is used up, xreadgroup raises
        # CancelledError, as if the consumer were being shut down.
        self.reads: list[Any] = []
        self.block_forever = False
        # What xautoclaim returns, one item per call: [next_id, [(id, fields)], []].
        # With no script left it answers "nothing pending" (next_id 0-0).
        self.claims: list[Any] = []
        # How many times Redis delivered each message (xpending_range)
        self.deliveries: dict[str, int] = {}

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

    async def xreadgroup(
        self, groupname: str, consumername: str, streams: dict, **kwargs: Any
    ) -> Any:
        self.calls.append(("xreadgroup", groupname, consumername, streams))
        if self.block_forever:
            await asyncio.Event().wait()  # until the task is cancelled
        if not self.reads:
            raise asyncio.CancelledError()
        item = self.reads.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def xautoclaim(
        self,
        name: str,
        groupname: str,
        consumername: str,
        min_idle_time: int,
        start_id: str = "0-0",
        count: int | None = None,
        justid: bool = False,
    ) -> Any:
        self.calls.append(
            ("xautoclaim", name, groupname, consumername, min_idle_time, start_id)
        )
        item = self.claims.pop(0) if self.claims else ["0-0", [], []]
        if isinstance(item, BaseException):
            raise item
        return item

    async def xpending_range(
        self, name: str, groupname: str, min: str, max: str, count: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self.calls.append(("xpending_range", name, groupname, min, max))
        if min not in self.deliveries:
            return []
        return [
            {
                "message_id": min,
                "consumer": "someone",
                "time_since_delivered": 0,
                "times_delivered": self.deliveries[min],
            }
        ]

    def commands(self, name: str) -> list[tuple[Any, ...]]:
        """All recorded calls of one command, in order."""
        return [call for call in self.calls if call[0] == name]


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()
