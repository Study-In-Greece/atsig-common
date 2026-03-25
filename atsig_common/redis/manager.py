import asyncio
import json
from typing import Optional, Any
from redis.asyncio import Redis


class RedisManager:
    """Singleton wrapper για Redis connection."""

    _instance: Optional["RedisManager"] = None
    _lock = asyncio.Lock()

    def __init__(
        self, host: str, port: int, password: Optional[str] = None, db: int = 0
    ):
        self._redis: Optional[Redis] = None
        self.host = host
        self.port = port
        self.password = password
        self.db = db

    async def init_client(self):
        self._redis = Redis(
            host=self.host,
            port=self.port,
            password=self.password,
            db=self.db,
            decode_responses=True,
        )

    async def close_client(self):
        if self._redis:
            await self._redis.close()
            self._redis = None

    @property
    def redis(self) -> Redis:
        if self._redis is None:
            raise RuntimeError("Redis not initialized yet")
        return self._redis

    # ------------------------------
    # Common async helpers
    # ------------------------------
    async def get_json(self, key: str) -> Optional[Any]:
        data = await self.get(key)
        return json.loads(data) if data else None

    async def set_json(self, key: str, value: Any, expire: Optional[int] = None):
        await self.set(key, json.dumps(value), expire=expire)

    async def get(self, key: str) -> Optional[str]:
        return await self.redis.get(key)

    async def set(self, key: str, value: Any, expire: Optional[int] = None):
        await self.redis.set(name=key, value=value, ex=expire)

    async def delete(self, key: str):
        await self.redis.delete(key)

    async def exists(self, key: str) -> bool:
        return bool(await self.redis.exists(key))

    async def expire(self, key: str, expire: Optional[int] = None):
        await self.redis.expire(key, expire)

    async def hgetall(self, key: str) -> dict:
        return await self.redis.hgetall(key)

    async def hset(self, key: str, mapping: dict):
        await self.redis.hset(key, mapping=mapping)

    async def hdel(self, key: str, *keys: str):
        await self.redis.hdel(key, *keys)

    def __getattr__(self, name):
        """
        Αν κάποιος καλέσει μια μέθοδο που δεν υπάρχει στον Manager (π.χ. xadd),
        στείλε την απευθείας στο εσωτερικό redis object.
        """
        return getattr(self.redis, name)
