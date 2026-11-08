from atsig_common.redis.uni_cache import UniCache
from atsig_common.redis.uni_cache_keys import (
    DEPT_KEY,
    SCHOOL_KEY,
    UNI_HASH_KEY,
    invalidate_uni_cache,
)

from .test_uni_cache_ttl import DictRedis, StubUniApi


class DeletingRedis(DictRedis):
    async def delete(self, key):
        self.data.pop(key, None)
        self.ttl.pop(key, None)


async def _filled() -> DeletingRedis:
    redis = DeletingRedis()
    cache = UniCache(redis, StubUniApi())
    await cache.get_departments_by_university_ids_cached([10])
    await cache.get_departments_by_school_id_cached(5)
    await cache.get_departments_by_ids_cached([1, 2])
    redis.data["department:99"] = "{}"  # an unrelated entry
    return redis


def test_the_cache_and_the_invalidation_share_the_key_templates():
    cache = UniCache(DictRedis(), StubUniApi())

    assert (cache.DEPT_KEY, cache.SCHOOL_KEY, cache.UNI_HASH_KEY) == (
        DEPT_KEY,
        SCHOOL_KEY,
        UNI_HASH_KEY,
    )


async def test_invalidating_a_department_drops_its_entry_its_school_and_its_map_line():
    redis = await _filled()

    ok = await invalidate_uni_cache(redis, department_ids=[1], school_ids=[5])

    assert ok is True
    assert "department:1" not in redis.data
    assert "school_departments:5" not in redis.data
    assert "department:2" in redis.data
    assert "department:99" in redis.data
    assert redis.hashes[UNI_HASH_KEY] == {"2": "10"}


async def test_invalidating_a_university_empties_its_part_of_the_map_only():
    redis = await _filled()
    redis.hashes[UNI_HASH_KEY]["7"] = "20"

    await invalidate_uni_cache(redis, university_ids=[10])

    assert redis.hashes[UNI_HASH_KEY] == {"7": "20"}
    assert "department:1" in redis.data  # the entries are the caller's to name


async def test_invalidation_with_nothing_to_drop_touches_nothing():
    redis = await _filled()
    before = (dict(redis.data), {k: dict(v) for k, v in redis.hashes.items()})

    assert await invalidate_uni_cache(redis) is True

    assert (dict(redis.data), {k: dict(v) for k, v in redis.hashes.items()}) == before


async def test_a_redis_failure_is_logged_not_raised():
    class Broken:
        async def delete(self, key):
            raise ConnectionError("down")

    assert await invalidate_uni_cache(Broken(), department_ids=[1]) is False
