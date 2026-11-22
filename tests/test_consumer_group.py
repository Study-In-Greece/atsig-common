import asyncio

import pytest
from redis.exceptions import ResponseError

from atsig_common.redis.consumer import BaseRedisConsumer


def make_consumer(fake_redis, **kwargs):
    return BaseRedisConsumer(fake_redis, stream_name="events", group_name="g", **kwargs)


async def test_new_group_starts_at_the_beginning_of_the_stream(fake_redis):
    await make_consumer(fake_redis)._ensure_consumer_group()

    assert fake_redis.commands("xgroup_create") == [
        ("xgroup_create", "events", "g", "0", True)
    ]


async def test_group_start_id_can_be_overridden(fake_redis):
    await make_consumer(fake_redis, group_start_id="$")._ensure_consumer_group()

    assert fake_redis.commands("xgroup_create")[0][3] == "$"


async def test_existing_group_is_left_alone(fake_redis):
    await make_consumer(fake_redis)._ensure_consumer_group()
    # a second start finds the group (BUSYGROUP) and must not raise
    await make_consumer(fake_redis)._ensure_consumer_group()

    assert len(fake_redis.commands("xgroup_create")) == 2


async def test_a_lost_group_is_created_again_and_the_loop_goes_on(fake_redis):
    consumer = make_consumer(fake_redis, loop_error_delay=0)
    # The group exists at the start; then Redis loses it (NOGROUP on the next read)
    fake_redis.reads = [
        ResponseError("NOGROUP No such key 'events' or consumer group 'g'"),
        None,
    ]

    with pytest.raises(asyncio.CancelledError):
        await consumer.run()

    # created at the start, and again after the NOGROUP
    assert len(fake_redis.commands("xgroup_create")) == 2
    # it kept reading: two reads that were scripted, plus the one that cancels
    assert len(fake_redis.commands("xreadgroup")) == 3


async def test_nogroup_does_not_count_as_a_failure_of_redis(fake_redis):
    import asyncio

    import pytest

    consumer = make_consumer(fake_redis, max_loop_failures=1, loop_error_delay=0)
    fake_redis.reads = [ResponseError("NOGROUP lost"), ResponseError("NOGROUP lost")]

    # with max_loop_failures=1 any counted failure would raise ResponseError
    with pytest.raises(asyncio.CancelledError):
        await consumer.run()


async def test_another_response_error_is_still_a_failure(fake_redis):
    import pytest

    consumer = make_consumer(fake_redis, max_loop_failures=1, loop_error_delay=0)
    fake_redis.reads = [ResponseError("WRONGTYPE something else")]

    with pytest.raises(ResponseError):
        await consumer.run()
