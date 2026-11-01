import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jwcrypto import jwk, jwt

from atsig_common.auth.decode import (
    TokenVerifier,
    adecode_token,
    decode_token,
    get_verifier,
)
from atsig_common.auth.keycloak import create_keycloak_client
from atsig_common.exceptions import ServiceUnavailableError

KEY_1 = jwk.JWK.generate(kty="RSA", size=2048, kid="key-1")
KEY_2 = jwk.JWK.generate(kty="RSA", size=2048, kid="key-2")
STRANGER = jwk.JWK.generate(kty="RSA", size=2048, kid="key-1")  # same kid, other key


class FakeRealm:
    """A Keycloak realm: certs() returns the public keys, and counts the calls."""

    def __init__(self, *keys):
        self.keys = list(keys)
        self.certs_calls = 0
        self.certs_threads: list[int] = []
        self.down = False

    def certs(self):
        self.certs_calls += 1
        self.certs_threads.append(threading.get_ident())
        if self.down:
            raise ConnectionError("realm is down")
        return {"keys": [json.loads(key.export_public()) for key in self.keys]}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_token(key, alg="RS256", **claims):
    claims = {"sub": "u1", "exp": int(time.time()) + 300, **claims}
    token = jwt.JWT(header={"alg": alg, "kid": key.get("kid")}, claims=claims)
    token.make_signed_token(key)
    return token.serialize()


def status_of(error: pytest.ExceptionInfo) -> int:
    return error.value.status_code


def test_a_valid_token_gives_its_claims():
    verifier = TokenVerifier(FakeRealm(KEY_1))

    assert verifier.decode(make_token(KEY_1, email="a@x.gr"))["email"] == "a@x.gr"


def test_the_keys_are_fetched_once_and_reused():
    realm = FakeRealm(KEY_1)
    verifier = TokenVerifier(realm)

    for _ in range(50):
        verifier.decode(make_token(KEY_1))

    assert realm.certs_calls == 1  # was one HTTP request per token


def test_the_keys_are_fetched_again_after_the_ttl():
    realm, clock = FakeRealm(KEY_1), Clock()
    verifier = TokenVerifier(realm, ttl=600, clock=clock)
    token = make_token(KEY_1)

    verifier.decode(token)
    clock.now += 599
    verifier.decode(token)
    assert realm.certs_calls == 1
    clock.now += 2
    verifier.decode(token)

    assert realm.certs_calls == 2


@pytest.mark.parametrize(
    "token_factory",
    [
        lambda: make_token(KEY_1, exp=int(time.time()) - 3600),  # expired
        lambda: make_token(STRANGER),  # known kid, signed by another key
        lambda: "not.a.jwt",
        lambda: "",
        lambda: make_token(KEY_1)[:-4] + "AAAA",  # altered signature
    ],
)
def test_an_invalid_token_is_a_401(token_factory):
    verifier = TokenVerifier(FakeRealm(KEY_1))

    with pytest.raises(HTTPException) as error:
        verifier.decode(token_factory())

    assert status_of(error) == 401
    assert error.value.detail == "Invalid authentication credentials"


def test_the_clock_difference_allowed_is_the_leeway():
    verifier = TokenVerifier(FakeRealm(KEY_1), leeway=60)

    verifier.decode(make_token(KEY_1, exp=int(time.time()) - 30))  # inside the leeway
    with pytest.raises(HTTPException):
        verifier.decode(make_token(KEY_1, exp=int(time.time()) - 120))


def test_a_token_signed_with_a_shared_secret_is_refused():
    secret = jwk.JWK(
        kty="oct", k="c2VjcmV0LXNlY3JldC1zZWNyZXQtc2VjcmV0LTEyMzQ1Ng", kid="key-1"
    )
    verifier = TokenVerifier(FakeRealm(KEY_1))

    with pytest.raises(HTTPException) as error:
        verifier.decode(make_token(secret, alg="HS256"))

    assert status_of(error) == 401


def test_a_rotated_key_is_found_by_fetching_the_keys_again():
    realm = FakeRealm(KEY_1)
    clock = Clock()
    verifier = TokenVerifier(realm, min_refresh_interval=30, clock=clock)
    verifier.decode(make_token(KEY_1))

    realm.keys = [KEY_1, KEY_2]  # Keycloak rotated: key-2 now signs the tokens
    clock.now += 31
    claims = verifier.decode(make_token(KEY_2))

    assert claims["sub"] == "u1"
    assert realm.certs_calls == 2


def test_unknown_key_ids_can_not_force_a_fetch_on_every_request():
    realm, clock = FakeRealm(KEY_1), Clock()
    verifier = TokenVerifier(realm, min_refresh_interval=30, clock=clock)
    verifier.decode(make_token(KEY_1))  # first fetch
    stranger = jwk.JWK.generate(kty="RSA", size=2048, kid="random-kid")

    for _ in range(5):  # an attacker sends tokens with a key id we do not know
        with pytest.raises(HTTPException):
            verifier.decode(make_token(stranger))
    assert realm.certs_calls == 1  # the first fetch was less than 30 s ago

    clock.now += 31
    with pytest.raises(HTTPException):
        verifier.decode(make_token(stranger))
    assert realm.certs_calls == 2  # one more, after the interval


def test_keycloak_down_at_the_first_token_is_a_503_not_a_401():
    realm = FakeRealm(KEY_1)
    realm.down = True

    with pytest.raises(ServiceUnavailableError):
        TokenVerifier(realm).decode(make_token(KEY_1))


def test_keycloak_down_after_the_ttl_keeps_the_cached_keys_in_use():
    realm, clock = FakeRealm(KEY_1), Clock()
    verifier = TokenVerifier(realm, ttl=600, min_refresh_interval=30, clock=clock)
    verifier.decode(make_token(KEY_1))

    realm.down = True
    clock.now += 700
    assert verifier.decode(make_token(KEY_1))["sub"] == "u1"  # still works
    calls = realm.certs_calls
    verifier.decode(make_token(KEY_1))
    assert realm.certs_calls == calls  # and does not hammer Keycloak

    clock.now += 31
    verifier.decode(make_token(KEY_1))
    assert realm.certs_calls == calls + 1  # tries again after the interval


def test_issuer_and_audience_are_not_checked_by_default():
    claims = TokenVerifier(FakeRealm(KEY_1)).decode(
        make_token(KEY_1, iss="https://other", aud="whatever")
    )

    assert claims["iss"] == "https://other"


def test_the_issuer_check_when_it_is_on():
    verifier = TokenVerifier(FakeRealm(KEY_1), issuer="https://sso/realms/x")

    verifier.decode(make_token(KEY_1, iss="https://sso/realms/x"))
    for wrong in ({"iss": "https://evil"}, {}):
        with pytest.raises(HTTPException):
            verifier.decode(make_token(KEY_1, **wrong))


def test_the_audience_check_accepts_a_string_or_a_list():
    verifier = TokenVerifier(FakeRealm(KEY_1), audience="applications")

    verifier.decode(make_token(KEY_1, aud="applications"))
    verifier.decode(make_token(KEY_1, aud=["account", "applications"]))
    for wrong in ({"aud": "account"}, {"aud": ["account"]}, {}):
        with pytest.raises(HTTPException):
            verifier.decode(make_token(KEY_1, **wrong))


def test_decode_token_uses_one_cached_verifier_per_client():
    realm = FakeRealm(KEY_1)

    for _ in range(5):
        decode_token(realm, make_token(KEY_1))

    assert realm.certs_calls == 1
    assert get_verifier(realm) is get_verifier(realm)


def test_create_keycloak_client_builds_the_verifier_from_the_settings():
    settings = SimpleNamespace(
        AUTHORIZATION_URL="http://kc",
        KEYCLOAK_CLIENT_ID="c",
        KEYCLOAK_REALM="r",
        KEYCLOAK_CLIENT_SECRET="s",
        KEYCLOAK_VERIFY_SSL=True,
        KEYCLOAK_EXPECTED_ISSUER="http://kc/realms/r",
        KEYCLOAK_EXPECTED_AUDIENCE="apps",
    )

    client = create_keycloak_client(settings)

    verifier = get_verifier(client)
    assert (verifier.issuer, verifier.audience) == ("http://kc/realms/r", "apps")


def test_without_the_new_settings_the_checks_stay_off():
    settings = SimpleNamespace(
        AUTHORIZATION_URL="http://kc",
        KEYCLOAK_CLIENT_ID="c",
        KEYCLOAK_REALM="r",
        KEYCLOAK_CLIENT_SECRET="s",
        KEYCLOAK_VERIFY_SSL=True,
    )

    verifier = get_verifier(create_keycloak_client(settings))

    assert (verifier.issuer, verifier.audience) == (None, None)


def test_a_client_without_certs_decodes_the_token_itself():
    class Double:
        def decode_token(self, token):
            if token != "ok":
                raise ValueError("bad")
            return {"sub": "u1"}

    assert decode_token(Double(), "ok") == {"sub": "u1"}
    with pytest.raises(HTTPException) as error:
        decode_token(Double(), "bad")
    assert status_of(error) == 401


async def test_the_async_decode_fetches_the_keys_in_a_thread_only_when_needed():
    realm = FakeRealm(KEY_1)
    main_thread = threading.get_ident()

    first = await adecode_token(realm, make_token(KEY_1))
    second = await adecode_token(realm, make_token(KEY_1))

    assert first["sub"] == second["sub"] == "u1"
    assert realm.certs_calls == 1
    assert realm.certs_threads[0] != main_thread


async def test_concurrent_async_decodes_fetch_the_keys_once():
    realm = FakeRealm(KEY_1)

    await asyncio.gather(*(adecode_token(realm, make_token(KEY_1)) for _ in range(10)))

    assert realm.certs_calls == 1


def test_a_route_answers_503_when_keycloak_is_down_and_nothing_is_cached():
    from fastapi import Depends, FastAPI
    from fastapi.security import OAuth2PasswordBearer
    from fastapi.testclient import TestClient

    from atsig_common.auth.dependencies import make_get_token_payload
    from atsig_common.fastapi_utils import setup_exception_handlers

    realm = FakeRealm(KEY_1)
    realm.down = True
    app = FastAPI()
    setup_exception_handlers(app)
    get_payload = make_get_token_payload(OAuth2PasswordBearer(tokenUrl="x"), realm)

    @app.get("/me")
    async def me(payload: dict = Depends(get_payload)):
        return {"sub": payload["sub"]}

    response = TestClient(app).get(
        "/me", headers={"Authorization": f"Bearer {make_token(KEY_1)}"}
    )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json() == {"detail": "The authentication service is not available."}

    realm.down = False  # Keycloak is back: the same request now works
    ok = TestClient(app).get(
        "/me", headers={"Authorization": f"Bearer {make_token(KEY_1)}"}
    )
    assert ok.status_code == 200


def test_a_realm_that_also_publishes_an_encryption_key_still_verifies_tokens():
    """Keycloak lists an `enc` key (RSA-OAEP) beside the signing key in its JWKS."""
    encryption_key = jwk.JWK.generate(kty="RSA", size=2048, kid="enc-1")
    realm = FakeRealm(KEY_1)

    def certs():
        public_signing = json.loads(KEY_1.export_public())
        public_signing.update({"use": "sig", "alg": "RS256"})
        public_enc = json.loads(encryption_key.export_public())
        public_enc.update({"use": "enc", "alg": "RSA-OAEP"})
        return {"keys": [public_enc, public_signing]}

    realm.certs = certs

    assert TokenVerifier(realm).decode(make_token(KEY_1))["sub"] == "u1"
