import asyncio
import json

import pytest

from atsig_common.redis import consumer as consumer_module
from atsig_common.redis.consumer import BaseRedisConsumer


class Recording(BaseRedisConsumer):
    def __init__(self, redis_manager, **kwargs):
        super().__init__(redis_manager, "events", "group", **kwargs)
        self.processed: list[str] = []
        self.fail_times = 0
        self.sleeps: list[tuple[float, bool]] = []

    async def process_message(self, message_id, action, payload):
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("transient")
        self.processed.append(message_id)


class Sleeps(list):
    """The (delay, a slot was held) of every sleep. Set `consumer` before the run."""

    consumer: BaseRedisConsumer | None = None


@pytest.fixture
def sleeps(monkeypatch):
    """Replaces asyncio.sleep: records each delay, and whether a slot was held."""
    recorded = Sleeps()

    async def fake_sleep(seconds):
        locked = recorded.consumer._semaphore.locked() if recorded.consumer else None
        recorded.append((seconds, locked))

    monkeypatch.setattr(consumer_module.asyncio, "sleep", fake_sleep)
    return recorded


def entry(message_id: str):
    """What xreadgroup returns for one message: a list of (stream, messages)."""
    return [("events", [(message_id, {"action": "sync", "data": json.dumps({})})])]


async def test_a_failing_message_does_not_hold_a_slot_while_it_waits(
    fake_redis, sleeps
):
    consumer = Recording(fake_redis, concurrency=1, max_retries=3, retry_delay=2)
    sleeps.consumer = consumer
    consumer.fail_times = 2

    await consumer._handle_message("1-0", {"action": "sync", "data": "{}"})

    assert consumer.processed == ["1-0"]
    assert sleeps == [(2, False), (2, False)]  # waited twice, slot free both times
    assert fake_redis.commands("xadd") == []


async def test_a_slow_failing_message_does_not_block_the_others(fake_redis):
    """With one slot, a message that is waiting to retry lets another one through."""
    consumer = Recording(fake_redis, concurrency=1, max_retries=2, retry_delay=0.2)
    consumer.fail_times = 1  # the first message to run fails once and waits 0.2 s

    started = asyncio.get_running_loop().time()
    await asyncio.gather(
        consumer._handle_message("1-0", {"action": "sync", "data": "{}"}),
        consumer._handle_message("2-0", {"action": "sync", "data": "{}"}),
    )

    # the second message was processed while the first one waited, not after it
    assert consumer.processed == ["2-0", "1-0"]
    assert asyncio.get_running_loop().time() - started < 0.5


async def test_run_gives_up_after_repeated_read_failures(fake_redis, sleeps):
    consumer = Recording(fake_redis, max_loop_failures=3)
    sleeps.consumer = consumer
    fake_redis.reads = [ConnectionError(), ConnectionError(), ConnectionError()]

    with pytest.raises(ConnectionError):
        await consumer.run()

    assert [delay for delay, _ in sleeps] == [5, 10]  # growing, none after giving up
    assert consumer._is_running is False


async def test_the_delay_grows_up_to_a_limit(fake_redis, sleeps):
    consumer = Recording(
        fake_redis, max_loop_failures=6, loop_error_delay=5, loop_error_max_delay=20
    )
    sleeps.consumer = consumer
    fake_redis.reads = [ConnectionError()] * 6

    with pytest.raises(ConnectionError):
        await consumer.run()

    assert [delay for delay, _ in sleeps] == [5, 10, 20, 20, 20]


async def test_a_successful_read_resets_the_count_of_failures(fake_redis, sleeps):
    consumer = Recording(fake_redis, max_loop_failures=2)
    sleeps.consumer = consumer
    fake_redis.reads = [
        ConnectionError(),
        None,  # a read that works resets the count
        ConnectionError(),
        entry("1-0"),
        ConnectionError(),
    ]

    with pytest.raises(asyncio.CancelledError):  # the script ended: not a give-up
        await consumer.run()

    assert consumer.processed == ["1-0"]


async def test_max_loop_failures_zero_never_gives_up(fake_redis, sleeps):
    consumer = Recording(fake_redis, max_loop_failures=0)
    sleeps.consumer = consumer
    fake_redis.reads = [ConnectionError()] * 30

    with pytest.raises(asyncio.CancelledError):
        await consumer.run()

    assert len(sleeps) == 30


async def test_cancelling_run_ends_the_task_as_cancelled(fake_redis):
    consumer = Recording(fake_redis)
    fake_redis.block_forever = True
    task = asyncio.create_task(consumer.run())
    await asyncio.sleep(0.05)  # inside xreadgroup now

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled()
    assert consumer._is_running is False


async def test_stop_ends_the_loop_after_the_batch_without_an_error(fake_redis):
    consumer = Recording(fake_redis)

    class StopAfterFirst(Recording):
        async def process_message(self, message_id, action, payload):
            self.stop()

    consumer = StopAfterFirst(fake_redis)
    fake_redis.reads = [entry("1-0"), entry("2-0")]

    await consumer.run()  # returns normally

    assert len(fake_redis.commands("xreadgroup")) == 1
    assert len(fake_redis.commands("xack")) == 1


async def test_the_error_text_of_a_failed_read_is_not_logged(
    fake_redis, sleeps, caplog
):
    consumer = Recording(fake_redis, max_loop_failures=2)
    sleeps.consumer = consumer
    fake_redis.reads = [
        ConnectionError("password=hunter2"),
        ConnectionError("password=hunter2"),
    ]

    with pytest.raises(ConnectionError):
        await consumer.run()

    assert "hunter2" not in caplog.text
    assert "ConnectionError" in caplog.text
