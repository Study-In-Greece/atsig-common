import httpx

from .http_manager import HttpClientManager
from ..exceptions import (
    AtsigError,
    UnauthorizedError,
    ForbiddenError,
    NotFoundError,
    ConflictError,
    BadRequestError,
)


class BaseAPI:
    def __init__(
        self,
        base_url: str,
        headers: dict = None,
        http_manager: HttpClientManager = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_headers = headers or {}
        self.http_manager = http_manager

    def _get_auth_headers(self) -> dict:
        """Override this in subclasses if needed"""
        return {}

    async def _request(self, method: str, endpoint: str, raw=False, **kwargs):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        # Singleton check για τον client
        from .http_manager import HttpClientManager

        manager = self.http_manager or HttpClientManager
        if manager.client is None or manager.client.is_closed:
            await manager.init_client()

        # Αυτόματο Merge Headers:
        # 1. Default Headers
        # 2. Auth Headers (από το subclass)
        # 3. Request specific headers
        request_headers = {
            **self.default_headers,
            **self._get_auth_headers(),
            **kwargs.pop("headers", {}),
        }

        try:
            response = await self.http_manager.client.request(
                method, url, headers=request_headers, **kwargs
            )

            # Αν όλα πήγαν καλά (2xx)
            if response.is_success:
                if raw:
                    return response.content
                if "application/json" in response.headers.get("Content-Type", ""):
                    return response.json()
                return response.text

            # Αν έχουμε σφάλμα, κάνουμε map στα δικά μας Exceptions
            try:
                error_data = response.json()
                detail = (
                    error_data.get("detail")
                    or error_data.get("message")
                    or response.text
                )
            except Exception:
                detail = response.text

            if response.status_code == 404:
                raise NotFoundError(detail)
            elif response.status_code == 403:
                raise ForbiddenError(detail)
            elif response.status_code == 401:
                raise UnauthorizedError(detail)
            elif response.status_code == 409:
                raise ConflictError(detail)
            elif response.status_code == 400:
                raise BadRequestError(detail)
            else:
                raise AtsigError(f"Remote API Error ({response.status_code}): {detail}")

        except httpx.RequestError as e:
            # Σφάλματα δικτύου (timeout, DNS, κλπ)
            raise AtsigError(f"Network error while calling {url}: {str(e)}")

    async def get(self, endpoint: str, params: dict = None, **kwargs):
        return await self._request("GET", endpoint, params=params, **kwargs)

    async def get_raw(self, endpoint: str, params: dict = None, **kwargs):
        return await self._request("GET", endpoint, params=params, raw=True, **kwargs)

    async def post(self, endpoint: str, data=None, json=None, **kwargs):
        return await self._request("POST", endpoint, data=data, json=json, **kwargs)

    async def put(self, endpoint: str, data=None, json=None, **kwargs):
        return await self._request("PUT", endpoint, data=data, json=json, **kwargs)

    async def delete(self, endpoint: str, **kwargs):
        return await self._request("DELETE", endpoint, **kwargs)
