"""
What every API did by hand in its main.py: logging, Sentry/GlitchTip, exception
handlers, request-context middleware, CORS and the debug route.

    init_observability(settings, "applications-api")   # before the app is created

    app = FastAPI(...)
    app.add_middleware(MultipartBodyLimitMiddleware, ...)   # innermost, if used
    setup_app(app, settings)                                 # logging, CORS: outer

`init_observability` needs no FastAPI: a worker (Celery, a stream consumer) uses it
too. FastAPI is imported only by `setup_app`.
"""

from __future__ import annotations

import logging
import logging.config
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from .logger.config import get_logging_config

if TYPE_CHECKING:
    from fastapi import FastAPI


def scrub_sentry_event(event: dict[str, Any], hint: Any = None) -> dict[str, Any]:
    """
    `before_send` hook: the URL of the request is replaced by its route template
    (`/references/{token}`) and the query string is dropped. Some paths carry a
    secret token, and Sentry would keep the real URL of every error.
    """
    request = event.get("request")
    if request:
        transaction = event.get("transaction") or ""
        url = request.get("url")
        if url and transaction.startswith("/"):
            parts = urlsplit(url)
            request["url"] = urlunsplit(
                (parts.scheme, parts.netloc, transaction, "", "")
            )
        request.pop("query_string", None)
    return event


def init_observability(
    settings: Any,
    service_name: str,
    *,
    traces_sample_rate: float = 0.1,
    server_name: str | None = None,
) -> bool:
    """
    Sets up the JSON logging, and Sentry/GlitchTip in production when a DSN is set.

    Args:
        server_name: The name Sentry shows for the process, to tell apart processes of
            the same service (e.g. the web app and its worker). Sentry's own default
            (the hostname) when it is not given.

    Returns:
        True when Sentry was started.
    """
    logging.config.dictConfig(
        get_logging_config(
            service_name,
            include_user_email=getattr(settings, "LOG_USER_EMAIL", True),
        )
    )

    if settings.ENVIRONMENT != "production" or not settings.GLITCHTIP_DSN:
        return False

    options: dict[str, Any] = {}
    if server_name:
        options["server_name"] = server_name

    sentry_sdk.init(
        dsn=settings.GLITCHTIP_DSN,
        environment=settings.ENVIRONMENT,
        integrations=[
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)
        ],
        traces_sample_rate=traces_sample_rate,
        before_send=scrub_sentry_event,
        **options,
    )
    return True


def setup_app(app: FastAPI, settings: Any, *, debug_route: bool | None = None) -> None:
    """
    Exception handlers, the request-context middleware and CORS.

    `add_middleware` wraps what was added before, so the middleware added last is
    the outermost. Add a body limit before calling this, so that its 400 still
    goes out through the logging and CORS middleware.

    Args:
        debug_route: Adds `GET /debug-error`, which raises an error, for testing the
            error reports. By default only when the environment is not production.
    """
    # Here and not at the top: a worker that uses only init_observability has no
    # FastAPI installed
    from fastapi.middleware.cors import CORSMiddleware

    from .fastapi_utils import setup_exception_handlers
    from .logger.middleware import LoggingContextMiddleware

    setup_exception_handlers(app)
    app.add_middleware(
        LoggingContextMiddleware,
        include_user_email=getattr(settings, "LOG_USER_EMAIL", True),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if debug_route is None:
        debug_route = settings.ENVIRONMENT != "production"
    if debug_route:

        @app.get("/debug-error", include_in_schema=False)
        async def debug_error():
            raise RuntimeError("Debug error, raised on purpose by /debug-error")
