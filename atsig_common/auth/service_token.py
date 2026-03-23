import time
from keycloak import KeycloakOpenID


class ServiceTokenManager:
    def __init__(self, keycloak_client: KeycloakOpenID):
        self._token = None
        self._expires_at = 0
        self.keycloak_client = keycloak_client

    def get_token(self):
        if self._token and time.time() < self._expires_at - 30:
            return self._token

        token_data = self.keycloak_client.token(grant_type="client_credentials")
        self._token = token_data["access_token"]

        self._expires_at = time.time() + token_data["expires_in"]

        return self._token


def create_service_token_manager(keycloak_client: KeycloakOpenID):
    return ServiceTokenManager(keycloak_client)