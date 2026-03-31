import asyncio
import json
from typing import Optional, Any
from redis.asyncio import Redis


class RedisManager:
    """
    A Singleton wrapper for managing an asynchronous Redis connection.

    This class ensures that only one instance of the manager exists (optional logic implementation)
    and provides convenient helper methods for common Redis operations like JSON
    serialization and hash manipulation.
    """

    _instance: Optional["RedisManager"] = None
    _lock = asyncio.Lock()

    def __init__(
        self, host: str, port: int, password: Optional[str] = None, db: int = 0
    ):
        """
        Initializes the RedisManager with connection details.

        Args:
            host (str): Redis server hostname.
            port (int): Redis server port.
            password (Optional[str]): Connection password if required. Defaults to None.
            db (int): Database index to use. Defaults to 0.
        """
        self._redis: Optional[Redis] = None
        self.host = host
        self.port = port
        self.password = password
        self.db = db

    async def init_client(self):
        """
        Initializes the underlying Redis client.

        Configures the client to decode responses into strings automatically.
        """
        self._redis = Redis(
            host=self.host,
            port=self.port,
            password=self.password,
            db=self.db,
            decode_responses=True,
        )

    async def close_client(self):
        """
        Gracefully closes the Redis connection and clears the internal client.
        """
        if self._redis:
            await self._redis.close()
            self._redis = None

    @property
    def redis(self) -> Redis:
        """
        The active Redis client instance.

        Returns:
            Redis: The initialized Redis client.

        Raises:
            RuntimeError: If the client has not been initialized via init_client().
        """
        if self._redis is None:
            raise RuntimeError("Redis not initialized yet")
        return self._redis

    # ------------------------------
    # Common async helpers
    # ------------------------------
    async def get_json(self, key: str) -> Optional[Any]:
        """
        Retrieves a value from Redis and parses it from JSON.

        Args:
            key (str): The Redis key.

        Returns:
            Optional[Any]: The parsed JSON data or None if the key doesn't exist.
        """
        data = await self.get(key)
        return json.loads(data) if data else None

    async def set_json(self, key: str, value: Any, expire: Optional[int] = None):
        """
        Serializes a value to JSON and stores it in Redis.

        Args:
            key (str): The Redis key.
            value (Any): The data to serialize and store.
            expire (Optional[int]): Expiration time in seconds.
        """
        await self.set(key, json.dumps(value), expire=expire)

    async def get(self, key: str) -> Optional[str]:
        """Fetches a string value for the given key."""
        return await self.redis.get(key)

    async def set(self, key: str, value: Any, expire: Optional[int] = None):
        """Stores a value in Redis with an optional expiration time."""
        await self.redis.set(name=key, value=value, ex=expire)

    async def delete(self, key: str):
        """Removes the specified key from Redis."""
        await self.redis.delete(key)

    async def exists(self, key: str) -> bool:
        """Checks if the specified key exists in Redis."""
        return bool(await self.redis.exists(key))

    async def expire(self, key: str, expire: Optional[int] = None):
        """Sets an expiration timeout on a key."""
        await self.redis.expire(key, expire)

    async def hgetall(self, key: str) -> dict:
        """Retrieves all fields and values of a hash stored at key."""
        return await self.redis.hgetall(key)

    async def hset(self, key: str, mapping: dict):
        """Sets multiple hash fields to their respective values."""
        await self.redis.hset(key, mapping=mapping)

    async def hdel(self, key: str, *keys: str):
        """Deletes one or more fields from a hash."""
        await self.redis.hdel(key, *keys)

    def __getattr__(self, name):
        """
        Dynamic attribute lookup for Redis commands.

        If a method is not explicitly defined in this Manager (e.g., xadd, pfadd),
        this proxy will attempt to call it directly on the underlying Redis client.
        """
        return getattr(self.redis, name)
