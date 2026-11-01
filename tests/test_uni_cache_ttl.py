import json

from atsig_common.redis.uni_cache import UniCache


class DictRedis:
    """In-memory stand-in for RedisManager: keeps the TTL of every key."""

    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int | None] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    async def get_json(self, key):
        raw = self.data.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key, value, expire=None):
        self.data[key] = json.dumps(value)
        self.ttl[key] = expire

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    async def hdel(self, key, *fields):
        for field in fields:
            self.hashes.get(key, {}).pop(field, None)

    async def expire(self, key, expire=None):
        self.ttl[key] = expire


class StubUniApi:
    def __init__(self):
        self.departments = [
            {"id": 1, "university_id": 10, "name": "A"},
            {"id": 2, "university_id": 10, "name": "B"},
        ]

    async def get_departments_by_university_ids(self, ids):
        return self.departments

    async def get_departments_by_school_id(self, school_id):
        return self.departments

    async def get_departments_by_ids(self, ids):
        return [d for d in self.departments if d["id"] in ids]

    async def get_department(self, department_id):
        return next(d for d in self.departments if d["id"] == department_id)


async def test_every_cached_key_has_a_ttl():
    redis = DictRedis()
    cache = UniCache(redis, StubUniApi())

    await cache.get_departments_by_university_ids_cached([10])
    await cache.get_departments_by_school_id_cached(5)
    await cache.get_departments_by_ids_cached([1])
    await cache.get_department_by_id_cached(2)

    assert redis.data, "nothing was cached"
    assert all(redis.ttl[key] == cache.CACHE_TTL for key in redis.data), redis.ttl
