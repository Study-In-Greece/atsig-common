import asyncio
import json
import threading
import time
import weakref
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, status
from jwcrypto import jwk, jwt
from keycloak import KeycloakOpenID

from ..exceptions import ServiceUnavailableError
from ..logger.config import get_logger

logger = get_logger("atsig_common.auth.decode")

# Only asymmetric algorithms: a token can never be accepted as signed with a
# shared secret (HMAC), whatever its header says.
ALLOWED_ALGORITHMS = [
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
]


class TokenVerifier:
    """
    Verifies the access tokens of a Keycloak realm with the keys of the realm
    (the JWKS), which it keeps in memory.

    The keys are fetched once and reused, instead of one HTTP request to Keycloak per
    token. They are fetched again when they are older than `ttl` seconds, or when a
    token names a key (`kid`) that is not in the cache, which is how a key rotation
    looks. That second refresh happens at most once per `min_refresh_interval`
    seconds, so a client that sends random key ids can not make us call Keycloak on
    every request. When a refresh fails the keys we have keep being used.

    Args:
        ttl: Seconds the fetched keys are used before they are fetched again.
        min_refresh_interval: Seconds between two refreshes caused by an unknown `kid`.
        leeway: Seconds of clock difference allowed in `exp` and `nbf`.
        issuer: When set, the `iss` claim must be exactly this (e.g.
            `https://sso.example.gr/realms/msc-applications`). Off by default:
            behind a proxy the issuer of the tokens is the PUBLIC address of Keycloak,
            which is not what this service uses to reach it.
        audience: When set, the `aud` claim must be this (or a list that holds it).
            Off by default: Keycloak puts `aud: account` in a token unless an audience
            mapper is configured on the client.
        clock: Returns the current time in seconds (replaced in tests).
    """

    def __init__(
        self,
        keycloak_client: KeycloakOpenID,
        *,
        ttl: float = 600,
        min_refresh_interval: float = 30,
        leeway: int = 60,
        issuer: str | None = None,
        audience: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.keycloak_client = keycloak_client
        self.ttl = ttl
        self.min_refresh_interval = min_refresh_interval
        self.leeway = leeway
        self.issuer = issuer
        self.audience = audience
        self._clock = clock

        self._keys: jwk.JWKSet | None = None
        self._fetched_at = 0.0
        self._last_attempt = float("-inf")
        self._lock = threading.Lock()

    def needs_refresh(self) -> bool:
        """True when the next verification would have to fetch the keys."""
        return self._keys is None or self._clock() - self._fetched_at > self.ttl

    def refresh(self) -> None:
        """
        Fetches the keys of the realm (a blocking HTTP request).

        Raises:
            ServiceUnavailableError: the keys could not be fetched and there are no
                keys in the cache to fall back on.
        """
        with self._lock:
            self._fetch_locked()

    def _fetch_locked(self) -> None:
        now = self._clock()
        self._last_attempt = now
        try:
            certs = self.keycloak_client.certs()
            self._keys = jwk.JWKSet.from_json(json.dumps(certs))
            self._fetched_at = now
        except Exception as e:
            if self._keys is None:
                logger.error(
                    f"[Auth] The signing keys could not be fetched: {type(e).__name__}"
                )
                raise ServiceUnavailableError(
                    "The authentication service is not available."
                ) from None
            # Keep the keys we have. Try again after `min_refresh_interval`, not on
            # every request.
            self._fetched_at = now - self.ttl + self.min_refresh_interval
            logger.warning(
                f"[Auth] Refreshing the signing keys failed ({type(e).__name__}), "
                "the cached keys stay in use."
            )

    def _keys_for(self, kid: str | None) -> jwk.JWKSet:
        with self._lock:
            now = self._clock()
            is_stale = self._keys is None or now - self._fetched_at > self.ttl
            # A key that is not in the cache: probably rotated. Look again, but not
            # more often than every `min_refresh_interval` seconds.
            is_unknown_key = (
                bool(kid)
                and self._keys is not None
                and self._keys.get_key(kid) is None
                and now - self._last_attempt >= self.min_refresh_interval
            )
            if is_stale or is_unknown_key:
                self._fetch_locked()
            return self._keys

    def decode(self, token: str) -> dict[str, Any]:
        """
        Returns the claims of a valid token.

        Raises:
            HTTPException: 401 when the token is not valid (bad signature, expired,
                malformed, wrong issuer or audience).
            ServiceUnavailableError: the keys of the realm are not available.
        """
        try:
            kid = jwt.JWT(jwt=token).token.jose_header.get("kid")
        except Exception:
            raise _invalid() from None

        keys = self._keys_for(kid)

        try:
            verified = jwt.JWT(jwt=token, algs=ALLOWED_ALGORITHMS)
            verified.leeway = self.leeway
            verified.validate(keys)
            claims = jwt.json_decode(verified.claims)
        except Exception:
            raise _invalid() from None

        if self.issuer and claims.get("iss") != self.issuer:
            raise _invalid()
        if self.audience:
            audience = claims.get("aud")
            accepted = audience == self.audience or (
                isinstance(audience, list) and self.audience in audience
            )
            if not accepted:
                raise _invalid()

        return claims


def _invalid() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


# One verifier per Keycloak client, so that the keys are shared by everything that
# uses the client. `create_keycloak_client` registers the one built from the settings.
_VERIFIERS: "weakref.WeakKeyDictionary[Any, TokenVerifier]" = (
    weakref.WeakKeyDictionary()
)


def register_verifier(keycloak_client: Any, verifier: TokenVerifier) -> TokenVerifier:
    _VERIFIERS[keycloak_client] = verifier
    return verifier


def get_verifier(keycloak_client: Any) -> TokenVerifier:
    verifier = _VERIFIERS.get(keycloak_client)
    if verifier is None:
        verifier = register_verifier(keycloak_client, TokenVerifier(keycloak_client))
    return verifier


def decode_token(keycloak_client: KeycloakOpenID, token: str) -> dict:
    """
    Decodes and validates a Keycloak JWT token.

    The keys of the realm are cached (see `TokenVerifier`), so a token is verified
    without a request to Keycloak. If the token is expired, has an invalid signature,
    or is otherwise malformed, it raises a 401 Unauthorized exception compliant with
    FastAPI standards. If the keys of the realm can not be fetched and none are
    cached, it raises ServiceUnavailableError (503): a Keycloak that is down is not
    the same as credentials that are wrong.

    A client without a `certs()` method (a test double) is asked to decode the token
    itself.
    """
    if not hasattr(keycloak_client, "certs"):
        try:
            return keycloak_client.decode_token(token=token)
        except Exception:
            raise _invalid() from None

    return get_verifier(keycloak_client).decode(token)


async def adecode_token(keycloak_client: KeycloakOpenID, token: str) -> dict:
    """
    `decode_token` for async code. Verifying a token costs microseconds, so it runs
    on the event loop; fetching the keys blocks on the network, so when they have to
    be fetched that happens in a thread.
    """
    if hasattr(keycloak_client, "certs"):
        verifier = get_verifier(keycloak_client)
        if verifier.needs_refresh():
            await asyncio.to_thread(_refresh_if_needed, verifier)
    return decode_token(keycloak_client, token)


def _refresh_if_needed(verifier: TokenVerifier) -> None:
    # Re-checked inside the thread: another request may have refreshed meanwhile
    if verifier.needs_refresh():
        verifier.refresh()
