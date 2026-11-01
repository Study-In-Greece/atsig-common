import logging

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from atsig_common.logger.middleware import LoggingContextMiddleware

TOKEN = "3f1c9a52-8d2e-4c1b-9a77-0d6f3b1e2a44"


def make_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(LoggingContextMiddleware)

    router = APIRouter()

    @router.get("/{token}")
    async def read_reference(token: str):
        return {"ok": True}

    @router.get("/{token}/boom")
    async def boom(token: str):
        raise RuntimeError("unexpected")

    app.include_router(router, prefix="/references")
    return TestClient(app, raise_server_exceptions=False)


def middleware_log(caplog, level: int | None = None) -> str:
    """Only what the middleware wrote (the test client logs the real URL itself)."""
    return " ".join(
        r.getMessage()
        for r in caplog.records
        if r.name == "atsig_common.logger.middleware"
        and (level is None or r.levelno == level)
    )


def test_access_log_uses_the_route_template_not_the_secret_token(caplog):
    with caplog.at_level(logging.INFO):
        response = make_client().get(f"/references/{TOKEN}")

    assert response.status_code == 200
    log = middleware_log(caplog, logging.INFO)
    assert '"GET /references/{token}"' in log
    assert TOKEN not in log


def test_unhandled_exception_log_does_not_hold_the_token_either(caplog):
    with caplog.at_level(logging.INFO):
        response = make_client().get(f"/references/{TOKEN}/boom")

    assert response.status_code == 500
    log = middleware_log(caplog)
    assert "Unhandled exception during GET /references/{token}/boom" in log
    assert TOKEN not in log


def test_unmatched_path_is_logged_shortened(caplog):
    with caplog.at_level(logging.INFO):
        make_client().get("/nowhere/" + "x" * 500)

    line = middleware_log(caplog, logging.INFO)
    assert "/nowhere/" in line
    assert len(line) < 400
