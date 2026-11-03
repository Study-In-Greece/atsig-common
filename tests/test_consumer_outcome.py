import logging
import socket

import pytest

from atsig_common.events import Actions, dlq_name
from atsig_common.redis.consumer import (
    BaseRedisConsumer,
    ConsumerOutcome,
    consumer_name_from_hostname,
)


class Returning(BaseRedisConsumer):
    def __init__(self, redis_manager, result):
        super().__init__(
            redis_manager, stream_name="calls_events", group_name="group", retry_delay=0
        )
        self.result = result

    async def process_message(self, message_id, action, payload):
        return self.result


def test_the_outcomes_are_the_values_the_dlq_replay_shows():
    assert ConsumerOutcome.applied == "applied"
    assert ConsumerOutcome.ignored == "ignored"
    assert [o.value for o in ConsumerOutcome] == ["applied", "ignored"]


@pytest.mark.parametrize(
    "result", [ConsumerOutcome.applied, ConsumerOutcome.ignored, None]
)
async def test_the_message_is_acked_whatever_the_outcome_is(fake_redis, result):
    consumer = Returning(fake_redis, result)

    await consumer._handle_message("1-0", {"action": "sync", "data": "{}"})

    assert len(fake_redis.commands("xack")) == 1
    assert fake_redis.commands("xadd") == []


async def test_the_outcome_is_logged(fake_redis, caplog):
    consumer = Returning(fake_redis, ConsumerOutcome.ignored)

    with caplog.at_level(logging.DEBUG):
        await consumer._handle_message("1-0", {"action": "sync", "data": "{}"})

    assert "ACKed successfully (ignored)" in caplog.text


def test_the_name_of_the_dlq_is_in_one_place(fake_redis):
    assert dlq_name("calls_events") == "calls_events_dlq"
    assert Returning(fake_redis, None).dlq_name == dlq_name("calls_events")
    assert Actions.UNREADABLE == "unreadable"


def test_the_consumer_name_from_the_hostname_is_the_same_every_time(fake_redis):
    assert consumer_name_from_hostname("sync") == f"sync_{socket.gethostname()}"
    assert consumer_name_from_hostname("sync") == consumer_name_from_hostname("sync")

    named = BaseRedisConsumer(
        fake_redis,
        stream_name="s",
        group_name="g",
        consumer_name=consumer_name_from_hostname("sync"),
    )
    assert named.consumer_name == f"sync_{socket.gethostname()}"

    # the default stays a random name per start
    first = BaseRedisConsumer(fake_redis, stream_name="s", group_name="g")
    second = BaseRedisConsumer(fake_redis, stream_name="s", group_name="g")
    assert first.consumer_name != second.consumer_name
