from fastapi.security import OAuth2AuthorizationCodeBearer


def create_oauth_scheme(server_url: str, realm: str, auto_error: bool = True):
    # Τα standard endpoints του Keycloak
    base_url = f"{server_url.rstrip('/')}/realms/{realm}/protocol/openid-connect"

    return OAuth2AuthorizationCodeBearer(
        authorizationUrl=f"{base_url}/auth",
        tokenUrl=f"{base_url}/token",
        refreshUrl=f"{base_url}/token",  # Πολύ χρήσιμο για το Swagger
        auto_error=auto_error,
    )
