import logging.config
import subprocess
import sys
from types import SimpleNamespace

import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atsig_common import observability
from atsig_common.observability import (
    init_observability,
    scrub_sentry_event,
    setup_app,
)


def settings(environment="development", dsn=None, origins=("*",)):
    return SimpleNamespace(
        ENVIRONMENT=environment, GLITCHTIP_DSN=dsn, CORS_ORIGINS=list(origins)
    )


def test_scrub_replaces_the_url_path_with_the_route_template():
    event = {
        "transaction": "/references/{token}",
        "request": {
            "url": "https://api.example.gr/references/3f1c9a52-8d2e?x=1",
            "query_string": "x=1",
        },
    }

    scrubbed = scrub_sentry_event(event)

    assert scrubbed["request"] == {"url": "https://api.example.gr/references/{token}"}


def test_scrub_leaves_events_without_a_request_alone():
    event = {"message": "boom"}

    assert scrub_sentry_event(event) == {"message": "boom"}


def test_init_does_not_start_sentry_outside_production(monkeypatch):
    configs, inits = [], []
    monkeypatch.setattr(logging.config, "dictConfig", configs.append)
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: inits.append(kw))

    started = init_observability(settings("development", dsn="https://x@y/1"), "svc")

    assert started is False and inits == []
    assert len(configs) == 1 and "svc" in configs[0]["loggers"]


def test_init_starts_sentry_in_production_with_the_scrub_hook(monkeypatch):
    inits = []
    monkeypatch.setattr(logging.config, "dictConfig", lambda config: None)
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: inits.append(kw))

    started = init_observability(settings("production", dsn="https://x@y/1"), "svc")

    assert started is True
    assert inits[0]["before_send"] is observability.scrub_sentry_event
    assert inits[0]["environment"] == "production"


def test_init_passes_the_server_name_only_when_it_is_given(monkeypatch):
    inits = []
    monkeypatch.setattr(logging.config, "dictConfig", lambda config: None)
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: inits.append(kw))
    production = settings("production", dsn="https://x@y/1")

    init_observability(production, "svc", server_name="svc-worker")
    init_observability(production, "svc")

    assert inits[0]["server_name"] == "svc-worker"
    assert "server_name" not in inits[1]


def test_init_needs_a_dsn_even_in_production(monkeypatch):
    monkeypatch.setattr(logging.config, "dictConfig", lambda config: None)

    assert init_observability(settings("production", dsn=None), "svc") is False


def make_client(conf) -> TestClient:
    app = FastAPI()
    setup_app(app, conf)
    return TestClient(app, raise_server_exceptions=False)


def test_debug_route_exists_outside_production_only():
    assert make_client(settings("development")).get("/debug-error").status_code == 500
    assert make_client(settings("production")).get("/debug-error").status_code == 404


def test_debug_route_can_be_forced():
    app = FastAPI()
    setup_app(app, settings("production"), debug_route=True)

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/debug-error").status_code == 500


def test_cors_origins_come_from_the_settings():
    client = make_client(settings(origins=("https://apply.example.gr",)))

    allowed = client.get("/nope", headers={"Origin": "https://apply.example.gr"})
    refused = client.get("/nope", headers={"Origin": "https://evil.example"})

    assert allowed.headers["access-control-allow-origin"] == "https://apply.example.gr"
    assert "access-control-allow-origin" not in refused.headers


def test_exception_handlers_are_installed():
    app = FastAPI()
    setup_app(app, settings())

    @app.post("/x")
    async def x(value: int):
        return value

    response = TestClient(app).post("/x", params={"value": "nope"})

    assert response.status_code == 422
    assert set(response.json()["detail"][0]) == {"type", "loc", "msg"}


# --- init_observability without FastAPI (0.7.2) ----------------------------------------


def _run_without_fastapi(body: str) -> subprocess.CompletedProcess:
    """Runs `body` in a new interpreter where fastapi and starlette can not be imported."""
    code = (
        "import sys\n"
        "sys.modules['fastapi'] = None\n"
        "sys.modules['starlette'] = None\n"
        "from types import SimpleNamespace\n"
        "settings = SimpleNamespace(ENVIRONMENT='development', GLITCHTIP_DSN=None,"
        " LOG_USER_EMAIL=False)\n" + body
    )
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )


def test_init_observability_needs_no_fastapi():
    """A worker without FastAPI (the Celery workers of the email-service)."""
    result = _run_without_fastapi(
        "from atsig_common.observability import init_observability, scrub_sentry_event\n"
        "assert init_observability(settings, 'email-worker') is False\n"
        "assert 'fastapi' not in [m for m in sys.modules if sys.modules[m] is not None]\n"
        "print('ok')\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")


def test_setup_app_without_fastapi_fails_clearly():
    result = _run_without_fastapi(
        "from atsig_common.observability import setup_app\n"
        "try:\n"
        "    setup_app(object(), settings)\n"
        "except ImportError:\n"
        "    print('ImportError')\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ImportError")
