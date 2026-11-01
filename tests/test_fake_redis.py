import pytest
from redis.exceptions import ResponseError


async def test_fake_redis_records_commands(fake_redis):
    await fake_redis.xgroup_create("s", "g", id="0", mkstream=True)
    await fake_redis.xack("s", "g", "1-0")

    assert fake_redis.commands("xgroup_create") == [
        ("xgroup_create", "s", "g", "0", True)
    ]
    assert fake_redis.commands("xack") == [("xack", "s", "g", "1-0")]


async def test_fake_redis_group_exists_like_redis(fake_redis):
    await fake_redis.xgroup_create("s", "g")
    with pytest.raises(ResponseError, match="BUSYGROUP"):
        await fake_redis.xgroup_create("s", "g")
