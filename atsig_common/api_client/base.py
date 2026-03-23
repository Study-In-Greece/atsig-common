import httpx
from fastapi import HTTPException

from .http_manager import HttpClientManager


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
            response = await manager.client.request(
                method, url, headers=request_headers, **kwargs
            )
            if response.status_code == 200:
                if raw:
                    return response.content
                # Return JSON if possible
                if "application/json" in response.headers.get("Content-Type", ""):
                    return response.json()
                return response.text
            else:
                # Attempt to parse JSON error detail if possible
                try:
                    error_json = response.json()
                    detail = (
                        error_json.get("detail")
                        or error_json.get("message")
                        or response.text
                    )
                except Exception:
                    detail = response.text
                raise HTTPException(status_code=response.status_code, detail=detail)
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Request error: {e}")

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
