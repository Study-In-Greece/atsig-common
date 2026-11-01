from atsig_common.redis.manager import RedisManager


class FakeRedisClient:
    def __init__(self):
        self.closed = 0

    async def aclose(self):
        self.closed += 1


async def test_redis_close_uses_aclose_and_clears_the_client():
    manager = RedisManager("localhost", 6379)
    client = FakeRedisClient()
    manager._redis = client

    await manager.close_client()

    assert client.closed == 1
    assert manager._redis is None
