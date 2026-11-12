"""
Server-side check of a Cloudflare Turnstile token (the bot protection of the public
forms). Needs the `http` extra (httpx).
"""

import logging

import httpx

from atsig_common.exceptions import BadRequestError, ServiceUnavailableError

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


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
