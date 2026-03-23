from fastapi import HTTPException, status
from keycloak import KeycloakOpenID


def decode_token(keycloak_client: KeycloakOpenID, token: str) -> dict:
    try:
        return keycloak_client.decode_token(token=token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
