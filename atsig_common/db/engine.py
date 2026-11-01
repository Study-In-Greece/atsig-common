from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_ENGINE_OPTIONS: dict[str, Any] = {
    "echo": False,
    "pool_size": 10,
    "max_overflow": 20,
    # Connections that the database or a firewall closed while idle are detected
    # before use, and replaced after an hour.
    "pool_pre_ping": True,
    "pool_recycle": 3600,
    # The values of a statement stay out of the text of SQLAlchemy errors. That
    # text goes to logs, Sentry and the DLQ, and it would hold emails and names.
    "hide_parameters": True,
}


def create_db_engine(database_url: str, **overrides: Any) -> AsyncEngine:
    """
    The async engine of a service, with the same defaults everywhere. Any option of
    `create_async_engine` can be overridden by keyword.

    Mind the pool when you scale: every process of a service has its own pool
    (`pool_size + max_overflow` connections), and the database has a limit of
    connections (PostgreSQL's max_connections).
    """
    return create_async_engine(database_url, **{**DEFAULT_ENGINE_OPTIONS, **overrides})


def create_session_factory(
    engine: AsyncEngine, *, expire_on_commit: bool = False
) -> async_sessionmaker:
    """
    The session factory of a service.

    `expire_on_commit=False` keeps the attributes of an object readable after the
    commit, which the services rely on today. New code should not depend on it:
    read what you need before the commit.
    """
    return async_sessionmaker(engine, expire_on_commit=expire_on_commit)
