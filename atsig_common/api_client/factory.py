from typing import Any, Optional, Protocol
from .http_manager import HttpClientManager
from .clients.uni_api import UniAPI
from .clients.users_api import UsersAPI
from ..auth.service_token import ServiceTokenManager


class APIClientSettingsProto(Protocol):
    # Τα ορίζουμε ως Optional για να μην "βαράει" το type checker
    # αν λείπουν από την κλάση των Settings ενός API
    UNI_API_URL: Optional[str] = None
    PROFILES_API_URL: Optional[str] = None


class APIClientFactory:
    def __init__(
        self,
        settings: APIClientSettingsProto,
        token_manager: Optional[ServiceTokenManager] = None,
    ):
        self.settings = settings
        self.token_manager = token_manager
        self.http_manager: type[HttpClientManager] = HttpClientManager

    def _get_url(self, setting_name: str) -> str:
        """Helper to retrieve URL based on setting_name"""
        url = getattr(self.settings, setting_name, None)
        if not url:
            raise ValueError(
                f"Configuration Error: '{setting_name}' is not defined in your settings. "
                f"You cannot initialize this API client."
            )
        return url

    def get_uni_api(self) -> UniAPI:
        base_url = self._get_url("UNI_API_URL")
        return UniAPI(base_url=base_url, http_manager=self.http_manager)

    def get_users_api(self) -> UsersAPI:
        base_url = self._get_url("PROFILES_API_URL")
        return UsersAPI(
            base_url=base_url,
            http_manager=self.http_manager,
            token_manager=self.token_manager,
        )
