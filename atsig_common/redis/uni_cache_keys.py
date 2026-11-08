"""
The Redis keys of the `UniCache`, and how to invalidate them.

This module does not import the `UniAPI` client, so a service that owns the data (the
uni-api) can drop the cache entries after a write without the `api_client` extra.
"""

from collections.abc import Iterable

from ..logger.config import get_logger
from .manager import RedisManager

logger = get_logger("atsig_common.redis.uni_cache_keys")

# Templates of the keys. `UniCache` reads and writes them, `invalidate_uni_cache` drops them.
DEPT_KEY = "department:{}"
SCHOOL_KEY = "school_departments:{}"
UNI_HASH_KEY = "department_university_map"


async def invalidate_uni_cache(
    redis: RedisManager,
    *,
    department_ids: Iterable[int] = (),
    school_ids: Iterable[int] = (),
    university_ids: Iterable[int] = (),
) -> bool:
    """
    Drop the cache entries that a change of the uni-api made stale. Never raises: a
    failure is logged (the type of the error only) and the entries expire with their TTL.

    - `department_ids`: the `department:{id}` entries (the cached dict also carries the
      school and the university of the department, so a change of either needs the ids
      of all its departments here) and their line in the department-to-university map.
    - `school_ids`: the `school_departments:{id}` entries.
    - `university_ids`: every department of these universities leaves the map, so the
      next lookup of the university asks the API again (a department that was added,
      moved or deleted changes who belongs to a university).

    Returns True if everything was dropped.
    """
    departments = sorted(set(department_ids))
    schools = sorted(set(school_ids))
    universities = {int(uni_id) for uni_id in university_ids}

    try:
        for department_id in departments:
            await redis.delete(DEPT_KEY.format(department_id))
        for school_id in schools:
            await redis.delete(SCHOOL_KEY.format(school_id))

        stale_map_fields = {str(department_id) for department_id in departments}
        if universities:
            mapping = await redis.hgetall(UNI_HASH_KEY)
            stale_map_fields.update(
                dep_id
                for dep_id, uni_id in mapping.items()
                if int(uni_id) in universities
            )
        if stale_map_fields:
            await redis.hdel(UNI_HASH_KEY, *sorted(stale_map_fields))
    except Exception as e:
        logger.warning(
            f"[UniCache] Invalidation failed ({type(e).__name__}); "
            "the entries expire with their TTL"
        )
        return False

    return True
