from atsig_common.api_client.base import BaseAPI
from atsig_common.api_client.http_manager import HttpClientManager
from atsig_common.auth.service_token import ServiceTokenManager


class UsersAPI(BaseAPI):
    def __init__(
        self,
        base_url: str,
        token_manager: ServiceTokenManager,
        http_manager: HttpClientManager,
    ):
        self.token_manager = token_manager
        super().__init__(base_url=base_url, http_manager=http_manager)

    def _get_auth_headers(self):
        token = self.token_manager.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def get_secretary(self, secretary_id: str):
        return await self.get(endpoint=f"/secretaries/{secretary_id}")

    async def get_secretaries_by_uuids(self, uuids: list[str]):
        return await self.get(
            endpoint=f"/secretaries/by_ids",
            params={"ids": uuids},
        )

    async def get_users_by_uuids(self, uuids: list[str]):
        return await self.get(
            endpoint=f"/applicants/by_ids",
            params={"ids": uuids},
        )

    async def get_applicant_profiles_by_uuids(self, uuids: list[str]):
        return await self.get(
            endpoint=f"/applicants/by_ids",
            params={"ids": uuids},
        )
