from typing import Protocol

from keycloak import KeycloakOpenID


class KeycloakSettingsProto(Protocol):
    """
    A structural protocol defining the required configuration for Keycloak.

    Any settings object passed to the factory must implement these attributes
    to ensure compatibility with the KeycloakOpenID client.

    Attributes:
        AUTHORIZATION_URL (str): The base URL of the Keycloak server.
        KEYCLOAK_CLIENT_ID (str): The client ID for the application.
        KEYCLOAK_REALM (str): The specific realm name in Keycloak.
        KEYCLOAK_CLIENT_SECRET (str): The client secret for confidential access.
        KEYCLOAK_VERIFY_SSL (bool): Whether to verify SSL certificates for requests.
    """

    AUTHORIZATION_URL: str
    KEYCLOAK_CLIENT_ID: str
    KEYCLOAK_REALM: str
    KEYCLOAK_CLIENT_SECRET: str
    KEYCLOAK_VERIFY_SSL: bool


# Keycloak Client (core, reusable)
def create_keycloak_client(settings: KeycloakSettingsProto) -> KeycloakOpenID:
    """
    Factory function to initialize a KeycloakOpenID client.

    Uses the provided settings object (following the KeycloakSettingsProto)
    to configure the core communication layer with the Keycloak server.

    Args:
        settings (KeycloakSettingsProto): An object containing the necessary
            Keycloak configuration parameters.

    Returns:
        KeycloakOpenID: A configured instance of the Keycloak client.
    """
    return KeycloakOpenID(
        server_url=settings.AUTHORIZATION_URL,
        client_id=settings.KEYCLOAK_CLIENT_ID,
        realm_name=settings.KEYCLOAK_REALM,
        client_secret_key=settings.KEYCLOAK_CLIENT_SECRET,
        verify=settings.KEYCLOAK_VERIFY_SSL,
    )
