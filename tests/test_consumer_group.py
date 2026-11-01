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
