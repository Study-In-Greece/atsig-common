import json

import pytest

from atsig_common.redis import producer as producer_module
from atsig_common.redis.consumer import BaseRedisConsumer
from atsig_common.redis.producer import EventProducer


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(producer_module.asyncio, "sleep", fake_sleep)
    return sleeps


class FlakyRedis:
    """xadd fails `failures` times, then works."""

    def __init__(self, failures=0):
        self.failures = failures
        self.calls = []

    async def xadd(self, name, fields, **kwargs):
        self.calls.append((name, fields, kwargs))
        if len(self.calls) <= self.failures:
            raise ConnectionError("redis is down")
        return "1-0"


async def test_emit_writes_action_and_json_data_without_trimming_by_default():
    redis = FlakyRedis()

    message_id = await EventProducer(redis).emit("events", "sync", {"id": 1})

    assert message_id == "1-0"
    (name, fields, kwargs) = redis.calls[0]
    assert name == "events"
    assert fields == {"action": "sync", "data": json.dumps({"id": 1})}
    assert kwargs == {}


async def test_maxlen_trims_approximately_and_the_call_overrides_the_default():
    redis = FlakyRedis()
    producer = EventProducer(redis, default_maxlen=1000)

    await producer.emit("events", "sync", {})
    await producer.emit("events", "sync", {}, maxlen=50)

    assert redis.calls[0][2] == {"maxlen": 1000, "approximate": True}
    assert redis.calls[1][2] == {"maxlen": 50, "approximate": True}


async def test_without_retries_a_failure_is_raised_at_once():
    redis = FlakyRedis(failures=1)

    with pytest.raises(ConnectionError):
        await EventProducer(redis).emit("events", "sync", {})

    assert len(redis.calls) == 1


async def test_retries_try_again_with_a_growing_delay(no_sleep):
    redis = FlakyRedis(failures=2)

    message_id = await EventProducer(redis).emit(
        "events", "sync", {}, retries=3, retry_delay=0.5
    )

    assert message_id == "1-0"
    assert len(redis.calls) == 3
    assert no_sleep == [0.5, 1.0]


async def test_retries_run_out_and_the_last_error_is_raised():
    redis = FlakyRedis(failures=10)

    with pytest.raises(ConnectionError):
        await EventProducer(redis).emit("events", "sync", {}, retries=2)

    assert len(redis.calls) == 3


async def test_a_pipeline_is_never_retried():
    class Pipe(FlakyRedis):
        pass

    pipe = Pipe(failures=1)

    with pytest.raises(ConnectionError):
        await EventProducer(FlakyRedis()).emit(
            "events", "sync", {}, pipe=pipe, retries=3
        )

    assert len(pipe.calls) == 1


async def test_emit_safe_retries_and_never_raises():
    flaky = FlakyRedis(failures=2)
    assert await EventProducer(flaky).emit_safe("events", "sync", {}) == "1-0"

    down = FlakyRedis(failures=10)
    assert await EventProducer(down).emit_safe("events", "sync", {}) is None
    assert len(down.calls) == 3  # 1 try + 2 retries


async def test_unserializable_payload_is_raised_without_touching_redis():
    class Bad:
        def __str__(self):
            raise ValueError("no")

    redis = FlakyRedis()

    with pytest.raises(ValueError):
        await EventProducer(redis).emit("events", "sync", {"x": Bad()})

    assert redis.calls == []


async def test_the_dlq_is_trimmed_only_when_dlq_maxlen_is_set(fake_redis):
    trimmed = BaseRedisConsumer(fake_redis, "events", "g", dlq_maxlen=500)
    plain = BaseRedisConsumer(fake_redis, "events", "g")

    await trimmed._send_to_dlq("1-0", {}, "error")
    await plain._send_to_dlq("2-0", {}, "error")

    first, second = fake_redis.commands("xadd")
    assert first[3] == {"maxlen": 500, "approximate": True}
    assert second[3] == {}
