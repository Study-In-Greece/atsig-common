import asyncio
import json

import pytest

from atsig_common.exceptions import NonRetryableError
from atsig_common.redis import consumer as consumer_module
from atsig_common.redis.consumer import BaseRedisConsumer


class Recording(BaseRedisConsumer):
    def __init__(self, redis_manager, **kwargs):
        super().__init__(redis_manager, "events", "group", retry_delay=0, **kwargs)
        self.processed: list[str] = []
        self.raises: Exception | None = None

    async def process_message(self, message_id, action, payload):
        if self.raises:
            raise self.raises
        self.processed.append(message_id)


def fields(**extra):
    return {"action": "sync", "data": json.dumps({}), **extra}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(consumer_module.asyncio, "sleep", fake_sleep)


async def run_until_script_ends(consumer):
    with pytest.raises(asyncio.CancelledError):
        await consumer.run()


async def test_pending_messages_are_reclaimed_when_the_consumer_starts(fake_redis):
    consumer = Recording(fake_redis, consumer_name="worker-1", reclaim_idle_ms=90_000)
    fake_redis.claims = [["0-0", [("7-0", fields())], []]]

    await run_until_script_ends(consumer)

    assert consumer.processed == ["7-0"]
    assert fake_redis.commands("xack") == [("xack", "events", "group", "7-0")]
    assert fake_redis.commands("xautoclaim")[0] == (
        "xautoclaim", "events", "group", "worker-1", 90_000, "0-0",
    )  # fmt: skip


async def test_the_scan_continues_from_the_cursor_until_it_ends(fake_redis):
    consumer = Recording(fake_redis)
    fake_redis.claims = [
        ["5-0", [("1-0", fields())], []],
        ["9-0", [("5-0", fields())], []],
        ["0-0", [("9-0", fields())], []],
    ]

    await run_until_script_ends(consumer)

    assert consumer.processed == ["1-0", "5-0", "9-0"]
    assert [call[5] for call in fake_redis.commands("xautoclaim")] == [
        "0-0",
        "5-0",
        "9-0",
    ]


async def test_a_cursor_that_does_not_move_ends_the_scan(fake_redis):
    consumer = Recording(fake_redis)
    fake_redis.claims = [["4-0", [], []], ["4-0", [], []], ["4-0", [], []]]

    await run_until_script_ends(consumer)

    assert len(fake_redis.commands("xautoclaim")) == 2  # 0-0 then 4-0, then it stops


async def test_a_message_over_the_delivery_limit_goes_to_the_dlq_not_to_the_handler(
    fake_redis,
):
    consumer = Recording(fake_redis, max_deliveries=5)
    fake_redis.claims = [["0-0", [("1-0", fields())], []]]
    fake_redis.deliveries = {"1-0": 6}

    await run_until_script_ends(consumer)

    assert consumer.processed == []
    (xadd,) = fake_redis.commands("xadd")
    assert xadd[1] == "events_dlq"
    assert xadd[2]["error"] == "Delivery limit reached (6 deliveries)"
    assert [c[0] for c in fake_redis.calls if c[0] in ("xadd", "xack")] == [
        "xadd",
        "xack",
    ]


async def test_a_message_at_the_delivery_limit_is_still_handled(fake_redis):
    consumer = Recording(fake_redis, max_deliveries=5)
    fake_redis.claims = [["0-0", [("1-0", fields())], []]]
    fake_redis.deliveries = {"1-0": 5}

    await run_until_script_ends(consumer)

    assert consumer.processed == ["1-0"]
    assert fake_redis.commands("xadd") == []


async def test_an_unknown_delivery_count_does_not_stop_the_message(fake_redis):
    consumer = Recording(fake_redis)
    fake_redis.claims = [["0-0", [("1-0", fields())], []]]  # no count in the fake

    await run_until_script_ends(consumer)

    assert consumer.processed == ["1-0"]


async def test_an_entry_trimmed_from_the_stream_is_acked_and_skipped(fake_redis):
    consumer = Recording(fake_redis)
    fake_redis.claims = [["0-0", [("1-0", None)], []]]

    await run_until_script_ends(consumer)

    assert consumer.processed == []
    assert fake_redis.commands("xack") == [("xack", "events", "group", "1-0")]


async def test_a_failed_dlq_write_leaves_the_message_pending(fake_redis):
    """It used to be ACKed ("emergency ACK") and lost."""
    fake_redis.fail_xadd = True
    consumer = Recording(fake_redis)
    consumer.raises = NonRetryableError("deterministic")

    await consumer._handle_message("1-0", fields())

    assert fake_redis.commands("xack") == []


async def test_an_invalid_message_whose_dlq_write_fails_stays_pending(fake_redis):
    fake_redis.fail_xadd = True
    consumer = Recording(fake_redis)

    await consumer._handle_message("1-0", {"action": "sync"})

    assert fake_redis.commands("xack") == []


async def test_a_message_over_the_limit_whose_dlq_write_fails_stays_pending(
    fake_redis,
):
    fake_redis.fail_xadd = True
    consumer = Recording(fake_redis, max_deliveries=1)
    fake_redis.claims = [["0-0", [("1-0", fields())], []]]
    fake_redis.deliveries = {"1-0": 2}

    await run_until_script_ends(consumer)

    assert fake_redis.commands("xack") == []


async def test_reclaim_runs_again_every_interval(fake_redis):
    consumer = Recording(fake_redis, reclaim_interval_s=0)
    fake_redis.reads = [None, None]

    await run_until_script_ends(consumer)

    assert len(fake_redis.commands("xautoclaim")) == 3  # start + before each read


async def test_with_a_long_interval_it_runs_only_at_start(fake_redis):
    consumer = Recording(fake_redis, reclaim_interval_s=3600)
    fake_redis.reads = [None, None, None]

    await run_until_script_ends(consumer)

    assert len(fake_redis.commands("xautoclaim")) == 1


async def test_a_failing_reclaim_is_a_loop_failure_not_a_crash(fake_redis):
    consumer = Recording(fake_redis, max_loop_failures=3)
    fake_redis.claims = [ConnectionError(), ConnectionError(), ConnectionError()]

    with pytest.raises(ConnectionError):
        await consumer.run()


async def test_the_consumer_name_can_be_fixed_and_is_random_otherwise(fake_redis):
    fixed = Recording(fake_redis, consumer_name="email-1")
    first = Recording(fake_redis, consumer_prefix="w")
    second = Recording(fake_redis, consumer_prefix="w")

    assert fixed.consumer_name == "email-1"
    assert first.consumer_name != second.consumer_name
    assert first.consumer_name.startswith("w_")
