"""
The shared clients of a service, built from its settings and started and stopped
together. Each service had the same six files in `core/` (Keycloak, Redis, storage,
API clients) and the same lifespan; this is that, once.

    core = build_core(settings)

    app = FastAPI(lifespan=core.make_lifespan(engine.dispose))
    get_token_payload = make_get_token_payload(core.oauth2_scheme, core.keycloak)

A service that has nothing to wire (no Redis, no storage) leaves it out:
`build_core(settings, redis=False, storage=False)`.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from fastapi.security import OAuth2AuthorizationCodeBearer
from keycloak import KeycloakOpenID

from .api_client.factory import APIClientFactory
from .auth.keycloak import create_keycloak_client
from .auth.oauth import create_oauth_scheme
from .auth.service_token import ServiceTokenManager, create_service_token_manager
from .logger.config import get_logger
from .redis.manager import RedisManager
from .storage.s3 import S3Storage

logger = get_logger("atsig_common.bootstrap")


@dataclass
class Core:
    keycloak: KeycloakOpenID
    oauth2_scheme: OAuth2AuthorizationCodeBearer
    optional_oauth2_scheme: OAuth2AuthorizationCodeBearer
    token_manager: ServiceTokenManager
    redis: RedisManager | None = None
    storage: S3Storage | None = None
    api_factory: APIClientFactory | None = None
    _started: list[tuple[str, Callable[[], Awaitable[Any]]]] = field(
        default_factory=list, repr=False
    )

    def _resources(self) -> list[tuple[str, Callable, Callable]]:
        """(name, start, stop) of what this core owns, in the order of starting."""
        resources: list[tuple[str, Callable, Callable]] = []
        if self.api_factory is not None:
            manager = self.api_factory.http_manager
            resources.append(("http", manager.init_client, manager.close_client))
        if self.redis is not None:
            resources.append(("redis", self.redis.init_client, self.redis.close_client))
        if self.storage is not None:
            resources.append(("storage", self.storage.start, self.storage.stop))
        return resources

    async def start(self) -> None:
        """
        Starts the clients, in order. If one fails to start, the ones started before
        it are stopped and the error is raised (nothing is left open).
        """
        try:
            for name, start, stop in self._resources():
                await start()
                self._started.append((name, stop))
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        """
        Stops what was started, in reverse order. A client that fails to stop is
        logged (its type only) and does not prevent the others from stopping.
        """
        while self._started:
            name, stop = self._started.pop()
            try:
                await stop()
            except Exception as e:
                logger.error(f"[Core] Stopping '{name}' failed: {type(e).__name__}")

    def make_lifespan(
        self, *on_stop: Callable[[], Awaitable[Any]]
    ) -> Callable[[FastAPI], Any]:
        """
        A FastAPI lifespan: starts the clients, and stops them (and runs `on_stop`,
        e.g. `engine.dispose`) at shutdown, also when the application ended with an
        error.
        """

        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncIterator[None]:
            await self.start()
            try:
                yield
            finally:
                await self.stop()
                for callback in on_stop:
                    try:
                        await callback()
                    except Exception as e:
                        logger.error(
                            f"[Core] A shutdown step failed: {type(e).__name__}"
                        )

        return lifespan


def build_core(
    settings: Any,
    *,
    redis: bool = True,
    storage: bool = True,
    api_clients: bool = True,
) -> Core:
    """
    Builds the shared clients from the settings (nothing is started yet).

    Args:
        redis: Build the Redis connection (needs REDIS_SERVER in the settings).
        storage: Build the R2/S3 storage (needs the R2_* settings; both buckets are
            passed, a bucket that is not configured fails when it is first used).
        api_clients: Build the factory of the clients for profiles-api and uni-api
            (needs PROFILES_API_URL and/or UNI_API_URL in the settings).
    """
    keycloak = create_keycloak_client(settings)
    token_manager = create_service_token_manager(keycloak)

    redis_manager = None
    if redis:
        if not settings.REDIS_SERVER:
            raise ValueError("REDIS_SERVER is not set, but redis=True")
        redis_manager = RedisManager(
            host=settings.REDIS_SERVER,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
        )

    storage_client = None
    if storage:
        storage_client = S3Storage(
            r2_endpoint_url=settings.R2_ENDPOINT_URL,
            r2_access_key_id=settings.R2_ACCESS_KEY_ID,
            r2_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            r2_private_bucket=settings.R2_PRIVATE_BUCKET,
            r2_public_bucket=settings.R2_PUBLIC_BUCKET,
        )

    return Core(
        keycloak=keycloak,
        oauth2_scheme=create_oauth_scheme(
            server_url=settings.AUTHORIZATION_URL, realm=settings.KEYCLOAK_REALM
        ),
        optional_oauth2_scheme=create_oauth_scheme(
            server_url=settings.AUTHORIZATION_URL,
            realm=settings.KEYCLOAK_REALM,
            auto_error=False,
        ),
        token_manager=token_manager,
        redis=redis_manager,
        storage=storage_client,
        api_factory=(
            APIClientFactory(settings=settings, token_manager=token_manager)
            if api_clients
            else None
        ),
    )
