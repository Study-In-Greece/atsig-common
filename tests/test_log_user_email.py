import json
import logging
from types import SimpleNamespace

import jwt
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atsig_common.logger.config import UnifiedFormatter, get_logging_config
from atsig_common.logger.context import user_email_var, user_id_var
from atsig_common.observability import setup_app


def format_line(formatter: UnifiedFormatter) -> dict:
    record = logging.LogRecord("svc", logging.INFO, __file__, 1, "hello", None, None)
    return json.loads(formatter.format(record))


def test_the_email_is_in_every_line_by_default():
    user_id_var.set("u1")
    user_email_var.set("u1@example.com")
    try:
        line = format_line(UnifiedFormatter())
    finally:
        user_id_var.set(None)
        user_email_var.set(None)

    assert line["user_email"] == "u1@example.com"
    assert line["user_id"] == "u1"


def test_the_email_can_be_left_out_and_the_user_id_stays():
    user_id_var.set("u1")
    user_email_var.set("u1@example.com")
    try:
        line = format_line(UnifiedFormatter(include_user_email=False))
    finally:
        user_id_var.set(None)
        user_email_var.set(None)

    assert "user_email" not in line
    assert line["user_id"] == "u1"


def test_the_flag_travels_through_the_logging_config():
    on = get_logging_config("svc")
    off = get_logging_config("svc", include_user_email=False)

    assert on["formatters"]["standard"]["include_user_email"] is True
    assert off["formatters"]["standard"]["include_user_email"] is False


def run_request(include_user_email: bool) -> tuple[dict, list]:
    users, seen = [], {}
    original = sentry_sdk.set_user
    sentry_sdk.set_user = users.append
    try:
        app = FastAPI()
        setup_app(
            app,
            SimpleNamespace(
                ENVIRONMENT="production",
                CORS_ORIGINS=["*"],
                LOG_USER_EMAIL=include_user_email,
            ),
        )

        @app.get("/me")
        async def me():
            seen["email"] = user_email_var.get()
            return {}

        token = jwt.encode(
            {"sub": "u1", "email": "u1@example.com"},
            "test-key-not-a-secret-0123456789abcdef",
            "HS256",
        )
        TestClient(app).get("/me", headers={"Authorization": f"Bearer {token}"})
    finally:
        sentry_sdk.set_user = original
    return seen, users


def test_middleware_keeps_the_email_out_of_the_context_and_sentry_when_off():
    seen, users = run_request(include_user_email=False)

    assert seen["email"] is None
    assert users[0] == {"id": "u1", "email": None}


def test_middleware_sets_the_email_by_default():
    seen, users = run_request(include_user_email=True)

    assert seen["email"] == "u1@example.com"
    assert users[0] == {"id": "u1", "email": "u1@example.com"}
