from atsig_common.api_client.base import BaseAPI
from atsig_common.api_client.http_manager import HttpClientManager


class UniAPI(BaseAPI):
    def __init__(self, base_url, http_manager: HttpClientManager):
        super().__init__(base_url=base_url, http_manager=http_manager)

    async def get_department(self, department_id: int | str):
        return await self.get(endpoint=f"/departments/{department_id}")

    async def get_departments_by_ids(self, ids: list[int]):
        return await self.get(endpoint="/departments/by_ids", params={"ids": ids})

    async def get_departments_by_university_ids(self, ids: list[int]):
        return await self.get(endpoint="/departments/by_uni_ids", params={"ids": ids})

    async def get_departments_by_school_id(self, school_id: int):
        response = await self.get(
            endpoint="/departments", params={"school_id": school_id, "limit": 100}
        )
        return response["items"]

    async def get_universities(self):
        response = await self.get(endpoint="/universities", params={"limit": 100})
        return response["items"]
