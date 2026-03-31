from typing import Any, Optional, Protocol
from .http_manager import HttpClientManager
from .clients.uni_api import UniAPI
from .clients.users_api import UsersAPI
from ..auth.service_token import ServiceTokenManager


class APIClientSettingsProto(Protocol):
    """
    A structural protocol for API configuration settings.

    Attributes are marked as Optional to prevent type-checker errors if a specific
    implementation class does not define all of them, while still providing
    IDE autocompletion and structural validation.
    """

    UNI_API_URL: Optional[str] = None
    PROFILES_API_URL: Optional[str] = None


class APIClientFactory:
    """
    Factory class responsible for instantiating and configuring various API clients.

    It centralizes the injection of settings, HTTP managers, and token managers
    into specific API service classes, ensuring consistent initialization across
    the application.
    """

    def __init__(
        self,
        settings: APIClientSettingsProto,
        token_manager: Optional[ServiceTokenManager] = None,
    ):
        """
        Initializes the factory with the required configuration and optional auth manager.

        Args:
            settings (APIClientSettingsProto): An object containing the base URLs
                for the external services.
            token_manager (Optional[ServiceTokenManager]): A manager to handle
                service-to-service authentication tokens.
        """
        self.settings = settings
        self.token_manager = token_manager
        self.http_manager: type[HttpClientManager] = HttpClientManager

    def _get_url(self, setting_name: str) -> str:
        """
        Internal helper to safely retrieve a URL from the settings object.

        Args:
            setting_name (str): The attribute name to look up in the settings.

        Returns:
            str: The configured URL.

        Raises:
            ValueError: If the requested setting is missing or empty.
        """
        url = getattr(self.settings, setting_name, None)
        if not url:
            raise ValueError(
                f"Configuration Error: '{setting_name}' is not defined in your settings. "
                f"You cannot initialize this API client."
            )
        return url

    def get_uni_api(self) -> UniAPI:
        """
        Creates and returns a configured instance of UniAPI.

        Returns:
            UniAPI: The client for University-related services.
        """
        base_url = self._get_url("UNI_API_URL")
        return UniAPI(base_url=base_url, http_manager=self.http_manager)

    def get_users_api(self) -> UsersAPI:
        """
        Creates and returns a configured instance of UsersAPI.

        This client is automatically injected with the ServiceTokenManager
        to handle authenticated requests.

        Returns:
            UsersAPI: The client for User Profile services.
        """
        base_url = self._get_url("PROFILES_API_URL")
        return UsersAPI(
            base_url=base_url,
            http_manager=self.http_manager,
            token_manager=self.token_manager,
        )
