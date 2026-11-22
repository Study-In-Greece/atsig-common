import asyncio
import logging
import os
import time

from atsig_common.redis import healthcheck, supervisor
from atsig_common.redis.supervisor import supervise

logger = logging.getLogger("test-supervisor")


class FakeConsumer:
    def __init__(self, behaviour: str = "forever"):
        self.behaviour = behaviour
        self.stopped = False
        self.last_loop_at: float | None = time.monotonic()

    async def run(self):
        if self.behaviour == "returns":
            return
        if self.behaviour == "raises":
            raise RuntimeError("boom")
        while not self.stopped:
            await asyncio.sleep(0.01)

    def stop(self):
        self.stopped = True


async def test_stop_request_ends_with_code_0():
    stop = asyncio.Event()
    consumers = {"a": FakeConsumer(), "b": FakeConsumer()}
    task = asyncio.create_task(
        supervise(consumers, stop, logger, shutdown_timeout=1, heartbeat_file=None)
    )
    await asyncio.sleep(0.05)
    stop.set()

    assert await task == 0
    assert all(consumer.stopped for consumer in consumers.values())


async def test_a_consumer_that_ends_stops_the_others_with_code_1():
    consumers = {"a": FakeConsumer("returns"), "b": FakeConsumer()}

    code = await supervise(
        consumers, asyncio.Event(), logger, shutdown_timeout=1, heartbeat_file=None
    )

    assert code == 1
    assert consumers["b"].stopped


async def test_a_consumer_that_raises_gives_code_1():
    code = await supervise(
        {"a": FakeConsumer("raises")},
        asyncio.Event(),
        logger,
        shutdown_timeout=1,
        heartbeat_file=None,
    )

    assert code == 1


async def test_heartbeat_is_written_while_the_consumers_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "HEARTBEAT_INTERVAL", 0.01)
    path = str(tmp_path / "heartbeat")
    stop = asyncio.Event()
    task = asyncio.create_task(
        supervise(
            {"a": FakeConsumer()},
            stop,
            logger,
            shutdown_timeout=1,
            heartbeat_file=path,
        )
    )
    await asyncio.sleep(0.1)
    stop.set()
    await task

    assert os.path.exists(path)
    assert healthcheck.is_healthy(path, max_age=5)


async def test_no_heartbeat_when_a_consumer_is_stuck(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "HEARTBEAT_INTERVAL", 0.01)
    monkeypatch.setattr(supervisor, "HEARTBEAT_STALE_AFTER", 1.0)
    path = str(tmp_path / "heartbeat")
    stuck = FakeConsumer()
    stuck.last_loop_at = time.monotonic() - 100
    stop = asyncio.Event()
    task = asyncio.create_task(
        supervise({"a": stuck}, stop, logger, shutdown_timeout=1, heartbeat_file=path)
    )
    await asyncio.sleep(0.1)
    stop.set()
    await task

    assert not os.path.exists(path)


def test_healthcheck_exit_codes(tmp_path):
    path = tmp_path / "heartbeat"
    assert healthcheck.main(["--file", str(path)]) == 1  # missing

    path.write_text("x")
    assert healthcheck.main(["--file", str(path), "--max-age", "60"]) == 0

    old = time.time() - 600
    os.utime(path, (old, old))
    assert healthcheck.main(["--file", str(path), "--max-age", "60"]) == 1
