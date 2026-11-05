from dataclasses import dataclass

import pytest
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import OAuth2PasswordBearer
from fastapi.testclient import TestClient

from atsig_common.auth.context import BaseAuthContext
from atsig_common.auth.dependencies import (
    build_auth_context,
    make_get_auth,
    make_get_auth_context,
    make_get_optional_auth_context,
    make_get_policy,
    make_get_token_payload,
)

GOOD = {
    "sub": "u1",
    "email": "u1@example.com",
    "groups": ["/Applicants", "/Evaluators"],
    "given_name": "Ada",
    "family_name": "Lovelace",
}


class FakeKeycloak:
    """decode_token(token) returns the claims registered for that token."""

    def __init__(self):
        self.tokens: dict[str, dict] = {"good": GOOD}
        self.decodes = 0

    def decode_token(self, token: str) -> dict:
        self.decodes += 1
        if token not in self.tokens:
            raise ValueError("bad token")
        return self.tokens[token]


@dataclass
class Ctx(BaseAuthContext):
    roles_loaded: bool = False

    async def load_role_contexts(self, session):
        self.roles_loaded = True
        return self


class Policy:
    def __init__(self, ctx):
        self.ctx = ctx


async def get_session():
    yield object()


@pytest.fixture
def keycloak():
    return FakeKeycloak()


def make_app(keycloak, **optional_kwargs) -> TestClient:
    oauth2 = OAuth2PasswordBearer(tokenUrl="x")
    optional = OAuth2PasswordBearer(tokenUrl="x", auto_error=False)

    get_token_payload = make_get_token_payload(oauth2, keycloak)
    get_auth = make_get_auth(get_token_payload)
    get_auth_context = make_get_auth_context(
        get_token_payload, get_session, context_cls=Ctx
    )
    get_policy = make_get_policy(get_auth_context, Policy)
    get_optional = make_get_optional_auth_context(
        optional, keycloak, get_session, context_cls=Ctx, **optional_kwargs
    )

    app = FastAPI()

    @app.get("/evaluators", dependencies=[Security(get_auth, scopes=["/Evaluators"])])
    async def evaluators(policy: Policy = Depends(get_policy)):
        return {"email": policy.ctx.email, "roles_loaded": policy.ctx.roles_loaded}

    @app.get("/secretary", dependencies=[Security(get_auth, scopes=["/Secretary"])])
    async def secretary():
        return {}

    @app.get("/maybe")
    async def maybe(ctx: Ctx | None = Depends(get_optional)):
        return {"user": ctx.email if ctx else None}

    # The pattern of the programmes-api: the scope check, and the policy built from the
    # optional context
    @app.get(
        "/scoped-optional", dependencies=[Security(get_auth, scopes=["/Evaluators"])]
    )
    async def scoped_optional(ctx: Ctx | None = Depends(get_optional)):
        return {"user": ctx.email if ctx else None}

    # The other order: the optional context runs before the scope check
    @app.get(
        "/optional-first",
        dependencies=[
            Depends(get_optional),
            Security(get_auth, scopes=["/Evaluators"]),
        ],
    )
    async def optional_first():
        return {}

    return TestClient(app)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_the_token_is_decoded_once_for_scope_and_context(keycloak):
    client = make_app(keycloak)

    response = client.get("/evaluators", headers=bearer("good"))

    assert response.status_code == 200
    assert response.json() == {"email": "u1@example.com", "roles_loaded": True}
    assert keycloak.decodes == 1  # was 2: get_auth and get_auth_context


def test_wrong_group_is_403_and_bad_token_is_401(keycloak):
    client = make_app(keycloak)

    assert client.get("/secretary", headers=bearer("good")).status_code == 403
    assert client.get("/secretary", headers=bearer("nope")).status_code == 401
    assert client.get("/secretary").status_code == 401


def test_strict_context_refuses_a_token_without_required_claims(keycloak):
    keycloak.tokens["partial"] = {"sub": "u2", "groups": ["/Evaluators"]}
    client = make_app(keycloak)

    response = client.get("/evaluators", headers=bearer("partial"))

    assert response.status_code == 401
    assert response.json()["detail"] == "Token is missing required claim(s): email"


def test_build_auth_context_non_strict_fills_missing_claims_with_empty_values():
    context = build_auth_context({"sub": "u"}, strict=False)

    assert (context.sub, context.email, context.groups) == ("u", "", [])
    assert (context.given_name, context.family_name) == ("", "")


def test_build_auth_context_reads_the_department_id():
    context = build_auth_context({**GOOD, "department_id": "7"}, context_cls=Ctx)

    assert isinstance(context, Ctx)
    assert context.department_id == 7


def test_invalid_department_id_is_refused_in_strict_mode_only():
    payload = {**GOOD, "department_id": "abc"}

    with pytest.raises(HTTPException) as error:
        build_auth_context(payload)
    assert error.value.status_code == 401
    assert build_auth_context(payload, strict=False).department_id is None


def test_optional_context_without_a_token_is_none(keycloak):
    assert make_app(keycloak).get("/maybe").json() == {"user": None}


def test_optional_context_with_a_valid_token_gives_the_user(keycloak):
    client = make_app(keycloak)

    assert client.get("/maybe", headers=bearer("good")).json() == {
        "user": "u1@example.com"
    }


def test_optional_context_invalid_token_is_anonymous_by_default(keycloak):
    client = make_app(keycloak)

    assert client.get("/maybe", headers=bearer("expired")).json() == {"user": None}


def test_optional_context_invalid_token_can_be_a_401(keycloak):
    client = make_app(keycloak, on_invalid="401")

    assert client.get("/maybe", headers=bearer("expired")).status_code == 401
    assert client.get("/maybe").json() == {"user": None}


def test_scope_check_and_optional_context_decode_the_token_once(keycloak):
    client = make_app(keycloak)

    response = client.get("/scoped-optional", headers=bearer("good"))

    assert response.json() == {"user": "u1@example.com"}
    assert keycloak.decodes == 1  # was 2: get_auth and the optional context


def test_optional_context_first_then_scope_check_decode_once(keycloak):
    client = make_app(keycloak)

    assert client.get("/optional-first", headers=bearer("good")).status_code == 200
    assert keycloak.decodes == 1


def test_the_payload_is_kept_for_one_request_only(keycloak):
    client = make_app(keycloak)

    client.get("/scoped-optional", headers=bearer("good"))
    client.get("/scoped-optional", headers=bearer("good"))

    assert keycloak.decodes == 2


def test_a_token_that_fails_is_not_kept(keycloak):
    """The optional context treats it as anonymous; the scope check still refuses it."""
    client = make_app(keycloak)

    response = client.get("/optional-first", headers=bearer("expired"))

    assert response.status_code == 401
    assert keycloak.decodes == 2  # decoded again, and failed again, by the scope check
