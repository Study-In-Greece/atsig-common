import json

import pytest

from atsig_common.exceptions import NonRetryableError
from atsig_common.redis.consumer import BaseRedisConsumer


class RecordingConsumer(BaseRedisConsumer):
    def __init__(self, redis_manager, **kwargs):
        super().__init__(
            redis_manager,
            stream_name="events",
            group_name="group",
            retry_delay=0,
            **kwargs,
        )
        self.processed: list[tuple[str, dict]] = []

    async def process_message(self, message_id, action, payload):
        if action == "poison":
            raise NonRetryableError("deterministic failure")
        self.processed.append((action, payload))


def dlq_error(fake_redis) -> str:
    (xadd,) = fake_redis.commands("xadd")
    assert xadd[1] == "events_dlq"
    return xadd[2]["error"]


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ({"action": "sync"}, "missing 'action' or 'data'"),
        ({"data": "{}"}, "missing 'action' or 'data'"),
        ({"action": "sync", "data": "{not json"}, "'data' is not valid JSON"),
        ({"action": "sync", "data": json.dumps([1, 2])}, "'data' is not a JSON object"),
        ({"action": "sync", "data": json.dumps("text")}, "'data' is not a JSON object"),
    ],
)
async def test_invalid_envelope_goes_to_dlq_then_ack(fake_redis, raw, reason):
    consumer = RecordingConsumer(fake_redis)

    await consumer._handle_message("1-0", raw)

    assert consumer.processed == []
    assert dlq_error(fake_redis) == f"Invalid message: {reason}"
    # the DLQ write comes before the ACK, so the entry is never lost
    assert [call[0] for call in fake_redis.calls] == ["xadd", "xack"]


async def test_undecodable_bytes_go_to_dlq_without_values(fake_redis):
    consumer = RecordingConsumer(fake_redis)

    await consumer._handle_message("1-0", {b"action": b"\xff\xfe", b"data": b"{}"})

    assert (
        dlq_error(fake_redis)
        == "Invalid message: unreadable entry (UnicodeDecodeError)"
    )
    assert len(fake_redis.commands("xack")) == 1


async def test_valid_message_is_processed_and_acked_without_dlq(fake_redis):
    consumer = RecordingConsumer(fake_redis)

    await consumer._handle_message(
        "1-0", {"action": "sync", "data": json.dumps({"id": 7})}
    )

    assert consumer.processed == [("sync", {"id": 7})]
    assert fake_redis.commands("xadd") == []
    assert len(fake_redis.commands("xack")) == 1


async def test_non_retryable_error_still_goes_to_dlq_then_ack(fake_redis):
    consumer = RecordingConsumer(fake_redis)

    await consumer._handle_message("1-0", {"action": "poison", "data": "{}"})

    assert dlq_error(fake_redis) == "deterministic failure"
    assert [call[0] for call in fake_redis.calls] == ["xadd", "xack"]
