from fastapi import HTTPException, status
from keycloak import KeycloakOpenID


def decode_token(keycloak_client: KeycloakOpenID, token: str) -> dict:
    """
    Decodes and validates a Keycloak JWT token.

    This function attempts to decode the provided token using the Keycloak client.
    If the token is expired, has an invalid signature, or is otherwise malformed,
    it raises a 401 Unauthorized exception compliant with FastAPI standards.

    Args:
        keycloak_client (KeycloakOpenID): The Keycloak client instance used for
            decoding and cryptographic validation.
        token (str): The raw JWT token string to be decoded.

    Returns:
        dict: The decoded payload of the token containing user claims and scopes.

    Raises:
        HTTPException: If the token is invalid or cannot be decoded, returns
            a 401 status code with a 'WWW-Authenticate' header.
    """
    try:
        # Attempt to decode the token using the public keys from Keycloak
        return keycloak_client.decode_token(token=token)
    except Exception:
        # If any error occurs during decoding, treat it as an unauthorized access attempt
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
