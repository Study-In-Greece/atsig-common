from typing import List, Dict, Optional
from .manager import RedisManager
from ..api_client.clients.uni_api import UniAPI
from ..logger.config import get_logger

logger = get_logger("atsig_common.redis.uni_cache")


class UniCache:
    def __init__(self, redis: RedisManager, uni_api: UniAPI):
        self.redis = redis
        self.uni_api = uni_api

        # Templates
        self.CACHE_TTL = 3600  # 1 hour
        self.DEPT_KEY = "department:{}"
        self.SCHOOL_KEY = "school_departments:{}"
        self.UNI_HASH_KEY = "department_university_map"

    async def update_department_university_map(self, departments: list[dict]):
        if not departments:
            return

        logger.info(
            f"[UniCache] Updating university map for {len(departments)} departments"
        )

        # find which universities these belong to
        uni_ids = {
            dep["university_id"] for dep in departments if dep.get("university_id")
        }
        existing_map = await self.redis.hgetall(self.UNI_HASH_KEY)

        # remove old departments for these universities
        to_delete = [
            dep_id for dep_id, u_id in existing_map.items() if int(u_id) in uni_ids
        ]
        if to_delete:
            logger.debug(
                f"[UniCache] Removing {len(to_delete)} stale mappings from hash"
            )
            await self.redis.hdel(self.UNI_HASH_KEY, *to_delete)

        # now add fresh mappings
        mapping = {
            str(dep["id"]): str(dep["university_id"])
            for dep in departments
            if dep.get("university_id")
        }
        await self.redis.hset(self.UNI_HASH_KEY, mapping=mapping)
        await self.redis.expire(self.UNI_HASH_KEY, self.CACHE_TTL)
        logger.info("[UniCache] University map update completed")

    async def get_departments_by_ids_cached(
        self, department_ids: List[int]
    ) -> Dict[int, dict]:
        departments = {}
        missing_ids = []
        """Fetch department data from cache or external API if missing."""

        for dep_id in department_ids:
            key = self.DEPT_KEY.format(dep_id)
            data = await self.redis.get_json(key)
            if data:
                logger.info(f"[UniCache] Cache HIT for department:{dep_id}")
                departments[dep_id] = data
            else:
                logger.warning(f"[UniCache] Cache MISS for department:{dep_id}")
                missing_ids.append(dep_id)

        if missing_ids:
            logger.info(
                f"[UniCache] Fetching {len(missing_ids)} missing departments from UniAPI..."
            )
            api_deps = await self.uni_api.get_departments_by_ids(missing_ids)
            for dep in api_deps:
                dep_id = dep["id"]
                departments[dep_id] = dep
                await self.redis.set_json(
                    self.DEPT_KEY.format(dep_id), dep, expire=self.CACHE_TTL
                )
            logger.info(
                f"[UniCache] Successfully cached {len(api_deps)} new departments"
            )
        return departments

    async def get_departments_by_university_ids_cached(
        self, university_ids: List[int]
    ) -> Dict[int, dict]:
        """
        Fetch all departments for the given university_ids, using Redis cache if available.
        Returns a dict: {department_id: department_dict}.
        """
        if not university_ids:
            return {}
        logger.info(
            f"[UniCache] Requesting departments for universities: {university_ids}"
        )
        departments: Dict[int, dict] = {}
        missing_unis: List[int] = []

        # Assuming Redis hash stores department_id → university_id mapping
        all_dep_map = await self.redis.hgetall(self.UNI_HASH_KEY)

        # First try to get department IDs for each university from Redis hash
        for uni_id in university_ids:
            # Collect department_ids that belong to this university
            uni_dep_ids = [
                int(dep_id)
                for dep_id, u_id in all_dep_map.items()
                if int(u_id) == uni_id
            ]

            if uni_dep_ids:
                logger.info(
                    f"[UniCache] Found {len(uni_dep_ids)} departments in hash for uni:{uni_id}"
                )
                # Fetch department data from cache
                cached_deps = await self.get_departments_by_ids_cached(uni_dep_ids)
                departments.update(cached_deps)
            else:
                logger.warning(f"[UniCache] No mapping found in hash for uni:{uni_id}")
                missing_unis.append(uni_id)

        # Fetch from API if missing universities
        if missing_unis:
            logger.warning(
                f"[UniCache] Cache MISS for universities {missing_unis}. Fetching from API..."
            )
            api_departments = await self.uni_api.get_departments_by_university_ids(
                missing_unis
            )
            for dep in api_departments:
                dep_id = dep["id"]
                departments[dep_id] = dep
                # Cache each department
                await self.redis.set_json(self.DEPT_KEY.format(dep_id), dep)

            # Update Redis hash map for department → university
            await self.update_department_university_map(api_departments)

        return departments

    async def get_departments_by_school_id_cached(
        self, school_id: int
    ) -> dict[int, dict]:
        """
        Fetch department data for a school from cache or external API if missing.
        Returns a dict: {department_id: department_dict}.
        """
        cache_key = self.SCHOOL_KEY.format(school_id)

        cached_data = await self.redis.get_json(cache_key)
        if cached_data:
            logger.info(
                f"[UniCache] Cache HIT for school:{school_id} (found {len(cached_data)} depts)"
            )
            # Ensure keys are integers
            return {int(dep_id): dep for dep_id, dep in cached_data.items()}

        logger.warning(
            f"[UniCache] Cache MISS for school:{school_id}. Fetching from API..."
        )

        # Fetch from API
        school_departments = await self.uni_api.get_departments_by_school_id(school_id)
        department_map = {int(dep["id"]): dep for dep in school_departments}

        # Cache the dict
        await self.redis.set_json(cache_key, department_map)
        logger.info(
            f"[UniCache] Successfully cached {len(department_map)} departments for school:{school_id}"
        )
        return department_map

    async def get_department_by_id_cached(self, department_id: int) -> Optional[dict]:
        """
        Fetch a single department from cache or UniAPI.
        Returns the department dict or None if not found.
        """
        key = self.DEPT_KEY.format(department_id)

        # 1. Προσπάθεια ανάκτησης από τη Redis
        dep_data = await self.redis.get_json(key)

        if dep_data:
            logger.info(f"[UniCache] Cache HIT for department:{department_id}")
            return dep_data

        # 2. Αν δεν υπάρχει, χτυπάμε το UniAPI
        logger.warning(
            f"[UniCache] Cache MISS for department:{department_id}. Fetching from API..."
        )

        try:
            dep_data = await self.uni_api.get_department(department_id)

            if dep_data:
                # 3. Αποθήκευση στη Redis για επόμενη φορά
                await self.redis.set_json(key, dep_data, expire=self.CACHE_TTL)
                logger.info(
                    f"[UniCache] Successfully cached department:{department_id}"
                )
                return dep_data

            logger.error(f"[UniCache] Department:{department_id} not found in UniAPI")
            return None

        except Exception as e:
            logger.error(
                f"[UniCache] Failed to fetch department:{department_id} from API: {e}"
            )
            return None
