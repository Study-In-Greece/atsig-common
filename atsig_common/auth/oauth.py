from fastapi.security import OAuth2AuthorizationCodeBearer


def create_oauth_scheme(server_url: str, realm: str, auto_error: bool = True):
    """
    Creates an OAuth2 Authorization Code Bearer scheme for FastAPI.

    This scheme is used by FastAPI to integrate with the Swagger UI (OpenAPI),
    allowing users to authenticate via Keycloak directly from the browser.
    It automatically constructs the standard OpenID Connect (OIDC) endpoints
    for authorization and token exchange.

    Args:
        server_url (str): The base URL of the Keycloak server.
        realm (str): The specific realm name.
        auto_error (bool, optional): If True, FastAPI will automatically raise
            an error if the Authorization header is missing or invalid.
            Defaults to True.

    Returns:
        OAuth2AuthorizationCodeBearer: A configured security scheme for FastAPI
            dependency injection.
    """
    # Construct the standard OIDC base URL for the given realm
    # We strip any trailing slashes to ensure the path is formed correctly
    base_url = f"{server_url.rstrip('/')}/realms/{realm}/protocol/openid-connect"

    return OAuth2AuthorizationCodeBearer(
        authorizationUrl=f"{base_url}/auth",
        tokenUrl=f"{base_url}/token",
        refreshUrl=f"{base_url}/token",  # Πολύ χρήσιμο για το Swagger
        auto_error=auto_error,
    )
