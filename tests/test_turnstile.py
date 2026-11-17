import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from atsig_common import turnstile
from atsig_common.exceptions import BadRequestError, ServiceUnavailableError
from atsig_common.turnstile import make_require_turnstile, verify_turnstile


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


# ---------------------------------------------------------------- the dependency
def _app(secret):
    require = make_require_turnstile(lambda: secret)
    app = FastAPI()

    @app.post("/form", dependencies=[Depends(require)])
    async def form():
        return {"ok": True}

    return TestClient(app)


def test_dependency_with_an_empty_secret_lets_the_request_pass():
    assert _app(None).post("/form").status_code == 200
    assert _app("").post("/form").status_code == 200


def test_dependency_rejects_a_request_without_the_header():
    with pytest.raises(BadRequestError):
        _app("secret").post("/form")


def test_dependency_passes_the_token_the_secret_and_the_ip(monkeypatch):
    seen = {}

    async def fake(token, secret, *, remote_ip=None, **kwargs):
        seen.update(token=token, secret=secret, remote_ip=remote_ip)

    monkeypatch.setattr(turnstile, "verify_turnstile", fake)
    client = _app("secret")

    assert client.post("/form", headers={"X-Turnstile-Token": "tok"}).status_code == 200
    assert seen == {"token": "tok", "secret": "secret", "remote_ip": "testclient"}

    client.post(
        "/form",
        headers={"X-Turnstile-Token": "tok", "X-Forwarded-For": "9.9.9.9, 10.0.0.1"},
    )
    assert seen["remote_ip"] == "9.9.9.9"


def test_dependency_rejects_a_token_cloudflare_refuses(monkeypatch):
    async def refuse(token, secret, **kwargs):
        raise BadRequestError("Bot check failed. Please try again.")

    monkeypatch.setattr(turnstile, "verify_turnstile", refuse)
    with pytest.raises(BadRequestError):
        _app("secret").post("/form", headers={"X-Turnstile-Token": "bad"})
