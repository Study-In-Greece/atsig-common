from typing import Protocol

from keycloak import KeycloakOpenID


class KeycloakSettingsProto(Protocol):
    AUTHORIZATION_URL: str
    KEYCLOAK_CLIENT_ID: str
    KEYCLOAK_REALM: str
    KEYCLOAK_CLIENT_SECRET: str
    KEYCLOAK_VERIFY_SSL: bool


# Keycloak Client (core, reusable)
def create_keycloak_client(settings: KeycloakSettingsProto) -> KeycloakOpenID:
    return KeycloakOpenID(
        server_url=settings.AUTHORIZATION_URL,
        client_id=settings.KEYCLOAK_CLIENT_ID,
        realm_name=settings.KEYCLOAK_REALM,
        client_secret_key=settings.KEYCLOAK_CLIENT_SECRET,
        verify=settings.KEYCLOAK_VERIFY_SSL,
    )
