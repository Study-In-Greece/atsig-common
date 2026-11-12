import httpx
import pytest

from atsig_common.exceptions import BadRequestError, ServiceUnavailableError
from atsig_common.turnstile import verify_turnstile


def _transport(handler):
    return httpx.MockTransport(handler)


async def test_empty_secret_turns_the_check_off():
    def handler(request):
        raise AssertionError("Cloudflare must not be called")

    await verify_turnstile(None, None, transport=_transport(handler))
    await verify_turnstile("x", "", transport=_transport(handler))


async def test_missing_token_is_rejected_without_a_call():
    def handler(request):
        raise AssertionError("Cloudflare must not be called")

    with pytest.raises(BadRequestError):
        await verify_turnstile(None, "secret", transport=_transport(handler))


async def test_valid_token_passes_and_sends_secret_response_and_ip():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"success": True})

    await verify_turnstile(
        "tok", "secret", remote_ip="1.2.3.4", transport=_transport(handler)
    )
    assert "secret=secret" in seen["body"]
    assert "response=tok" in seen["body"]
    assert "remoteip=1.2.3.4" in seen["body"]


async def test_rejected_token_is_a_bad_request():
    def handler(request):
        return httpx.Response(200, json={"success": False})

    with pytest.raises(BadRequestError):
        await verify_turnstile("tok", "secret", transport=_transport(handler))


@pytest.mark.parametrize("status", [500, 429])
async def test_cloudflare_error_fails_closed(status):
    def handler(request):
        return httpx.Response(status)

    with pytest.raises(ServiceUnavailableError):
        await verify_turnstile("tok", "secret", transport=_transport(handler))


async def test_network_error_fails_closed():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(ServiceUnavailableError):
        await verify_turnstile("tok", "secret", transport=_transport(handler))


async def test_garbage_body_fails_closed():
    def handler(request):
        return httpx.Response(200, content=b"<html>")

    with pytest.raises(ServiceUnavailableError):
        await verify_turnstile("tok", "secret", transport=_transport(handler))
