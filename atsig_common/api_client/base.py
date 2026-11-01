import inspect
from urllib.parse import quote, urlsplit

import httpx

from ..exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    UpstreamError,
)
from ..logger.config import get_logger
from ..logger.context import current_request_id
from .http_manager import HttpClientManager

logger = get_logger("atsig_common.api_client")


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

    @staticmethod
    def path_segment(value: object) -> str:
        """
        One URL path segment made from a value (an id). Every character that has a
        meaning in a URL (`/`, `?`, `#`, `..`) is escaped, so a value can never
        reach another endpoint: these calls carry the token of the service.
        """
        return quote(str(value), safe="")

    @staticmethod
    def _correlation_headers() -> dict:
        """The id of the request being served, so a call can be followed across services."""
        request_id = current_request_id()
        return {"X-Request-ID": request_id} if request_id else {}

    def _get_auth_headers(self) -> dict:
        """
        Provides authentication-specific headers.

        Subclasses should override this method to inject Bearer tokens
        or API keys dynamically. It may be a plain method or a coroutine
        (`async def`), for a token that has to be fetched without blocking.

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
        auth_headers = self._get_auth_headers()
        if inspect.isawaitable(auth_headers):
            auth_headers = await auth_headers

        request_headers = {
            **self._correlation_headers(),
            **self.default_headers,
            **auth_headers,
            **kwargs.pop("headers", {}),
        }

        try:
            response = await manager.client.request(
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

            # What the user can fix or must know: the answer of the other service is
            # passed on as it is.
            if response.status_code == 404:
                raise NotFoundError(detail)
            elif response.status_code == 409:
                raise ConflictError(detail)
            elif response.status_code == 400:
                raise BadRequestError(detail)

            # Anything else (the 401/403 for the token of THIS service, a 422 for a
            # request this service built wrong, every 5xx) is not the fault of the
            # user. Answering it with the same status would tell the user "log in
            # again" for a problem between two services, and the body of the other
            # service would reach the user. It is a 502, and the status goes to the log.
            logger.error(
                f"[API client] {method} {urlsplit(url).path} answered "
                f"{response.status_code}"
            )
            raise UpstreamError()

        except httpx.RequestError as e:
            # Network errors (timeout, DNS, refused connection). The text of the error
            # holds the internal URL, so only its type is logged.
            logger.error(
                f"[API client] {method} {urlsplit(url).path} failed: {type(e).__name__}"
            )
            raise UpstreamError(
                status_code=504 if isinstance(e, httpx.TimeoutException) else 502
            ) from None

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
