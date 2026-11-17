"""
Server-side check of a Cloudflare Turnstile token (the bot protection of the public
forms). Needs the `http` extra (httpx).
"""

import logging
from collections.abc import Awaitable, Callable

import httpx

from atsig_common.exceptions import BadRequestError, ServiceUnavailableError

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
# The header of the request that carries the token of the form
TURNSTILE_HEADER = "X-Turnstile-Token"


async def verify_turnstile(
    token: str | None,
    secret: str | None,
    *,
    remote_ip: str | None = None,
    timeout: float = 5.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """
    Raises `BadRequestError` when the token is missing or rejected, and
    `ServiceUnavailableError` when Cloudflare can not be reached (the check fails
    closed: a public form must not be open while the check is down).

    An empty `secret` turns the check off (local development), so a service can
    declare `TURNSTILE_SECRET: str | None = None` and call this on every request.
    Nothing but the type of an error is logged, never the token.
    """
    if not secret:
        return
    if not token:
        raise BadRequestError("Bot check failed. Please try again.")

    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(TURNSTILE_VERIFY_URL, data=data)
            response.raise_for_status()
            success = response.json().get("success") is True
    except (httpx.HTTPError, ValueError) as e:
        logger.error("Turnstile verification unavailable: %s", type(e).__name__)
        raise ServiceUnavailableError(
            "The bot check is unavailable. Please try again later."
        ) from None

    if not success:
        raise BadRequestError("Bot check failed. Please try again.")


def make_require_turnstile(
    get_secret: Callable[[], str | None],
) -> Callable[..., Awaitable[None]]:
    """
    Builds the FastAPI dependency that checks the Turnstile token of a public route
    (needs the `fastapi` extra). The form sends the token in the `X-Turnstile-Token`
    header and the route declares the check, like it declares its authentication:

        require_turnstile = make_require_turnstile(lambda: settings.TURNSTILE_SECRET)

        @router.post("", dependencies=[Depends(require_turnstile)])

    `get_secret` is called on every request (so the settings are read when the
    request runs). An empty secret turns the check off. The IP of the caller goes to
    Cloudflare: the first address of `X-Forwarded-For` when a proxy set it, else the
    address of the connection. A forged address can only make the check fail, never
    pass.
    """
    from fastapi import Header, Request

    async def require_turnstile(
        request: Request,
        token: str | None = Header(default=None, alias=TURNSTILE_HEADER),
    ) -> None:
        await verify_turnstile(token, get_secret(), remote_ip=_caller_ip(request))

    return require_turnstile


def _caller_ip(request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else None
