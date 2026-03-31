import time
from keycloak import KeycloakOpenID


class ServiceTokenManager:
    """
    Manages the lifecycle of a Keycloak service token using client credentials.

    This class handles token retrieval and automatic caching, ensuring that
    the token is refreshed only when it is near expiration.
    """

    def __init__(self, keycloak_client: KeycloakOpenID):
        """
        Initializes the ServiceTokenManager with a Keycloak client.

        Args:
            keycloak_client (KeycloakOpenID): An instance of the KeycloakOpenID client
                used to communicate with the Keycloak server.
        """
        self._token = None
        self._expires_at = 0
        self.keycloak_client = keycloak_client

    def get_token(self):
        """
        Retrieves a valid access token.

        If a cached token exists and is not close to expiring (within a 30-second
        buffer), it returns the cached token. Otherwise, it requests a new
        token from Keycloak using the client credentials grant type.

        Returns:
            str: A valid access token for the service.
        """
        # Check if the current token is still valid with a 30-second safety margin
        if self._token and time.time() < self._expires_at - 30:
            return self._token
        # Request new token data from Keycloak
        token_data = self.keycloak_client.token(grant_type="client_credentials")
        self._token = token_data["access_token"]
        # Calculate the absolute expiration timestamp
        self._expires_at = time.time() + token_data["expires_in"]

        return self._token


def create_service_token_manager(keycloak_client: KeycloakOpenID):
    """
    Factory function to create a new ServiceTokenManager instance.

    Args:
        keycloak_client (KeycloakOpenID): The Keycloak client to be used by the manager.

    Returns:
        ServiceTokenManager: An initialized instance of ServiceTokenManager.
    """
    return ServiceTokenManager(keycloak_client)
