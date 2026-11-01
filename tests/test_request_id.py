import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atsig_common.logger.context import request_id_var
from atsig_common.logger.middleware import LoggingContextMiddleware, resolve_request_id


@pytest.mark.parametrize(
    "valid", ["abc123", "3f1c9a52-8d2e-4c1b-9a77-0d6f3b1e2a44", "svc.req_1-2", "a" * 64]
)
def test_a_valid_incoming_id_is_kept(valid):
    assert resolve_request_id(valid) == valid


@pytest.mark.parametrize(
    "invalid",
    [None, "", "a" * 65, "has space", 'quote"d', "<script>", "line\tbreak", "ελληνικά"],
)
def test_anything_else_is_replaced_by_a_generated_id(invalid):
    generated = resolve_request_id(invalid)

    assert generated != invalid
    assert len(generated) == 8 and generated.isalnum()


def make_client():
    seen = {}
    app = FastAPI()
    app.add_middleware(LoggingContextMiddleware)

    @app.get("/ping")
    async def ping():
        seen["request_id"] = request_id_var.get()
        return {}

    return TestClient(app), seen


def test_the_valid_id_reaches_the_context_and_the_response(caplog):
    client, seen = make_client()

    with caplog.at_level(logging.INFO):
        response = client.get("/ping", headers={"X-Request-ID": "req-42"})

    assert seen["request_id"] == "req-42"
    assert response.headers["X-Request-ID"] == "req-42"


def test_an_invalid_id_is_not_echoed_back():
    client, seen = make_client()

    response = client.get(
        "/ping", headers={"X-Request-ID": "<script>alert(1)</script>"}
    )

    assert "<script>" not in response.headers["X-Request-ID"]
    assert seen["request_id"] == response.headers["X-Request-ID"]


def test_the_placeholder_of_no_request_is_not_a_valid_id():
    assert resolve_request_id("-") != "-"
