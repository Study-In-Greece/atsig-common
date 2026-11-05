"""
FastAPI dependencies for Keycloak authentication, shared by the APIs.

Each API used to keep its own copy of these functions, and the copies drifted: one
checked the claims of the token, another failed with a KeyError (500) when a name
was missing, and a request decoded the token twice (once for the scope check, once
for the user context).

Here the token is decoded ONCE per request: the decoded payload is kept in
`request.state`, and the scope check, the context, the policy and the optional
context all read it from there, whichever of them runs first. (FastAPI's own cache of dependencies is not enough: a dependency that
is resolved below a `Security(..., scopes=[...])` gets a different cache key than the
same dependency resolved elsewhere, so it would run twice.)

    get_token_payload = make_get_token_payload(oauth2_scheme, keycloak_openid)
    get_auth = make_get_auth(get_token_payload)
    get_auth_context = make_get_auth_context(
        get_token_payload, get_session, context_cls=AuthContext
    )
    get_policy = make_get_policy(get_auth_context, AccessPolicy)
"""

from collections.abc import Callable
from typing import Any, Literal, TypeVar

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import SecurityScopes
from keycloak import KeycloakOpenID
from sqlalchemy.ext.asyncio import AsyncSession

from .context import BaseAuthContext
from .decode import adecode_token
from .groups import validate_user_groups

ContextT = TypeVar("ContextT", bound=BaseAuthContext)

REQUIRED_CLAIMS = ("sub", "email", "groups")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def build_auth_context(
    payload: dict[str, Any],
    *,
    context_cls: type[ContextT] = BaseAuthContext,  # type: ignore[assignment]
    strict: bool = True,
) -> ContextT:
    """
    Builds the context of the user from the claims of a decoded token. The role
    sub-contexts (secretary, evaluator, ...) are NOT loaded: call
    `await context.load_role_contexts(session)` for that.

    Args:
        payload: The decoded token.
        context_cls: The context class of the API (a subclass of BaseAuthContext).
        strict: When True, a token without `sub`, `email` or `groups`, or with a
            department_id that is not a number, is refused with a 401. When False,
            missing claims get empty values.
    """
    if strict:
        missing = [claim for claim in REQUIRED_CLAIMS if claim not in payload]
        if missing:
            raise _unauthorized(
                f"Token is missing required claim(s): {', '.join(missing)}"
            )

    raw_department_id = payload.get("department_id")
    try:
        department_id = int(raw_department_id) if raw_department_id else None
    except (TypeError, ValueError):
        if strict:
            raise _unauthorized("Token has an invalid department_id claim") from None
        department_id = None

    return context_cls(
        sub=payload.get("sub", ""),
        email=payload.get("email", ""),
        groups=payload.get("groups", []),
        given_name=payload.get("given_name", ""),
        family_name=payload.get("family_name", ""),
        department_id=department_id,
    )


async def _decode_once(
    request: Request, keycloak_client: KeycloakOpenID, token: str
) -> dict:
    """
    Decodes the token, or returns the payload already decoded for the same token in
    this request. Only a valid token is kept: one that fails is decoded (and fails)
    again by the next dependency that asks.
    """
    cached = getattr(request.state, "token_payload", None)
    if cached is not None and cached[0] == token:
        return cached[1]

    payload = await adecode_token(keycloak_client, token)
    request.state.token_payload = (token, payload)
    return payload


def make_get_token_payload(
    oauth2_scheme: Callable[..., Any], keycloak_client: KeycloakOpenID
) -> Callable[..., Any]:
    """The dependency that decodes the bearer token (401 when it is not valid)."""

    async def get_token_payload(
        request: Request, token: str = Depends(oauth2_scheme)
    ) -> dict:
        return await _decode_once(request, keycloak_client, token)

    return get_token_payload


def make_get_auth(get_token_payload: Callable[..., Any]) -> Callable[..., Any]:
    """
    The dependency for `Security(get_auth, scopes=[...])`: 403 when the user is not
    in one of the required groups. Returns the decoded token.
    """

    async def get_auth(
        security_scopes: SecurityScopes, payload: dict = Depends(get_token_payload)
    ) -> dict:
        is_valid = validate_user_groups(
            user_groups=payload.get("groups", []),
            required_scopes=security_scopes.scopes,
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User not in required group(s): {security_scopes.scopes}",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload

    return get_auth


def make_get_auth_context(
    get_token_payload: Callable[..., Any],
    get_session: Callable[..., Any],
    *,
    context_cls: type[ContextT] = BaseAuthContext,  # type: ignore[assignment]
    strict: bool = True,
) -> Callable[..., Any]:
    """The dependency that gives the context of the user, with its roles loaded."""

    async def get_auth_context(
        session: AsyncSession = Depends(get_session),
        payload: dict = Depends(get_token_payload),
    ) -> ContextT:
        context = build_auth_context(payload, context_cls=context_cls, strict=strict)
        await context.load_role_contexts(session)
        return context

    return get_auth_context


def make_get_optional_auth_context(
    optional_oauth2_scheme: Callable[..., Any],
    keycloak_client: KeycloakOpenID,
    get_session: Callable[..., Any],
    *,
    context_cls: type[ContextT] = BaseAuthContext,  # type: ignore[assignment]
    on_invalid: Literal["anonymous", "401"] = "anonymous",
    strict: bool = True,
) -> Callable[..., Any]:
    """
    The dependency for routes that may be called with or without a user. Without a
    token the result is None. With a token that is not valid (expired, bad
    signature, missing claims) the result depends on `on_invalid`:

    - "anonymous": None, the user is treated as not logged in.
    - "401": the request is refused with a 401.

    The token is decoded once per request: it shares the payload with
    `get_token_payload` (see `_decode_once`), so a protected route whose policy is
    built from the optional context decodes it once, not twice.
    """

    async def get_optional_auth_context(
        request: Request,
        session: AsyncSession = Depends(get_session),
        token: str | None = Depends(optional_oauth2_scheme),
    ) -> ContextT | None:
        if not token:
            return None
        try:
            payload = await _decode_once(request, keycloak_client, token)
            context = build_auth_context(
                payload, context_cls=context_cls, strict=strict
            )
        except HTTPException:
            if on_invalid == "401":
                raise
            return None
        await context.load_role_contexts(session)
        return context

    return get_optional_auth_context


def make_get_policy(
    get_auth_context: Callable[..., Any], policy_cls: type
) -> Callable[..., Any]:
    """The dependency that gives the access policy of the API for the user."""

    async def get_policy(context: BaseAuthContext = Depends(get_auth_context)):
        return policy_cls(ctx=context)

    return get_policy


__all__ = [
    "REQUIRED_CLAIMS",
    "build_auth_context",
    "make_get_auth",
    "make_get_auth_context",
    "make_get_optional_auth_context",
    "make_get_policy",
    "make_get_token_payload",
]
