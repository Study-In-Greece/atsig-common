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
    """
    Abstract base class for interacting with remote APIs.

    Provides core functionality for making asynchronous HTTP requests,
    automatic header management, and mapping remote HTTP errors to
    internal application exceptions.
    """

    def __init__(
        self,
        base_url: str,
        headers: dict = None,
        http_manager: HttpClientManager = None,
    ):
        """
        Initializes the API client.

        Args:
            base_url (str): The root URL for the remote service.
            headers (dict, optional): Default headers to include in every request.
            http_manager (HttpClientManager, optional): A manager for the HTTP client session.
        """
        self.base_url = base_url.rstrip("/")
        self.default_headers = headers or {}
        self.http_manager = http_manager

    def _get_auth_headers(self) -> dict:
        """
        Provides authentication-specific headers.

        Subclasses should override this method to inject Bearer tokens
        or API keys dynamically.

        Returns:
            dict: A dictionary of authentication headers.
        """
        return {}

    async def _request(self, method: str, endpoint: str, raw=False, **kwargs):
        """
        Internal core method to execute HTTP requests.

        Handles:
        1. URL construction.
        2. Lazy initialization of the HTTP client.
        3. Hierarchical Header Merging (Default -> Auth -> Specific).
        4. Response parsing (JSON/Text/Raw).
        5. Detailed error mapping.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        # Ensure the HTTP client is initialized (Singleton check)
        from .http_manager import HttpClientManager

        manager = self.http_manager or HttpClientManager
        if manager.client is None or manager.client.is_closed:
            await manager.init_client()

        # Automatic Header Merging Hierarchy:
        # 1. Global Default Headers (provided at __init__)
        # 2. Authentication Headers (provided by subclass logic)
        # 3. Request-specific headers (provided as arguments to the method)
        request_headers = {
            **self.default_headers,
            **self._get_auth_headers(),
            **kwargs.pop("headers", {}),
        }

        try:
            response = await self.http_manager.client.request(
                method, url, headers=request_headers, **kwargs
            )

            # Success path (HTTP 2xx)
            if response.is_success:
                if raw:
                    return response.content
                if "application/json" in response.headers.get("Content-Type", ""):
                    return response.json()
                return response.text

            # Error path: Map remote HTTP status codes to internal Exceptions
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
        """Executes an asynchronous GET request returning parsed data."""
        return await self._request("GET", endpoint, params=params, **kwargs)

    async def get_raw(self, endpoint: str, params: dict = None, **kwargs):
        """Executes an asynchronous GET request returning the raw binary content."""
        return await self._request("GET", endpoint, params=params, raw=True, **kwargs)

    async def post(self, endpoint: str, data=None, json=None, **kwargs):
        """Executes an asynchronous POST request."""
        return await self._request("POST", endpoint, data=data, json=json, **kwargs)

    async def put(self, endpoint: str, data=None, json=None, **kwargs):
        """Executes an asynchronous PUT request."""
        return await self._request("PUT", endpoint, data=data, json=json, **kwargs)

    async def delete(self, endpoint: str, **kwargs):
        """Executes an asynchronous DELETE request."""
        return await self._request("DELETE", endpoint, **kwargs)
