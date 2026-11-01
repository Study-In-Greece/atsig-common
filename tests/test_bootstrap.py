from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atsig_common.api_client.http_manager import HttpClientManager
from atsig_common.auth.decode import get_verifier
from atsig_common.bootstrap import build_core
from atsig_common.redis.manager import RedisManager
from atsig_common.storage.s3 import S3Storage


def make_settings(**overrides):
    values = {
        "AUTHORIZATION_URL": "http://kc",
        "KEYCLOAK_CLIENT_ID": "c",
        "KEYCLOAK_REALM": "msc",
        "KEYCLOAK_CLIENT_SECRET": "s",
        "KEYCLOAK_VERIFY_SSL": True,
        "REDIS_SERVER": "redis",
        "REDIS_PORT": 6379,
        "REDIS_PASSWORD": None,
        "R2_ENDPOINT_URL": "http://r2",
        "R2_ACCESS_KEY_ID": "k",
        "R2_SECRET_ACCESS_KEY": "s",
        "R2_PRIVATE_BUCKET": "private",
        "R2_PUBLIC_BUCKET": None,
        "PROFILES_API_URL": "http://profiles",
        "UNI_API_URL": "http://uni",
    }
    return SimpleNamespace(**{**values, **overrides})


class Events(list):
    """What the clients were asked to do, in order. `fail[label] = True` makes one fail."""

    def __init__(self):
        super().__init__()
        self.fail: dict[str, bool] = {}


@pytest.fixture
def events(monkeypatch):
    """Replaces the start/stop of every client with a recorder."""
    log = Events()
    fail = log.fail

    def recorder(label):
        async def call(*args, **kwargs):
            log.append(label)
            if fail.get(label):
                raise RuntimeError(f"{label} failed")

        return call

    monkeypatch.setattr(
        HttpClientManager, "init_client", staticmethod(recorder("start http"))
    )
    monkeypatch.setattr(
        HttpClientManager, "close_client", staticmethod(recorder("stop http"))
    )
    monkeypatch.setattr(RedisManager, "init_client", recorder("start redis"))
    monkeypatch.setattr(RedisManager, "close_client", recorder("stop redis"))
    monkeypatch.setattr(S3Storage, "start", recorder("start storage"))
    monkeypatch.setattr(S3Storage, "stop", recorder("stop storage"))
    return log


def test_build_core_wires_everything_from_the_settings():
    core = build_core(make_settings())

    assert core.redis.host == "redis" and core.redis.port == 6379
    assert core.storage.r2_private_bucket == "private"
    assert core.api_factory.get_users_api().base_url == "http://profiles"
    assert core.token_manager.keycloak_client is core.keycloak
    assert core.oauth2_scheme.auto_error is True
    assert core.optional_oauth2_scheme.auto_error is False
    assert get_verifier(core.keycloak).issuer is None  # the new checks stay off


def test_a_service_can_leave_out_what_it_does_not_use():
    core = build_core(make_settings(), redis=False, storage=False, api_clients=False)

    assert (core.redis, core.storage, core.api_factory) == (None, None, None)


def test_redis_without_a_server_is_refused_early():
    with pytest.raises(ValueError, match="REDIS_SERVER"):
        build_core(make_settings(REDIS_SERVER=None))


async def test_start_and_stop_follow_the_order_and_reverse_it(events):
    core = build_core(make_settings())

    await core.start()
    await core.stop()

    assert events == [
        "start http", "start redis", "start storage",
        "stop storage", "stop redis", "stop http",
    ]  # fmt: skip


async def test_a_failed_start_stops_what_was_already_started(events):
    events.fail["start storage"] = True
    core = build_core(make_settings())

    with pytest.raises(RuntimeError, match="storage failed"):
        await core.start()

    assert events == [
        "start http", "start redis", "start storage",
        "stop redis", "stop http",
    ]  # fmt: skip


async def test_a_failing_stop_does_not_keep_the_others_open(events, caplog):
    events.fail["stop redis"] = True
    core = build_core(make_settings())
    await core.start()

    await core.stop()

    assert events[-3:] == ["stop storage", "stop redis", "stop http"]
    assert "Stopping 'redis' failed: RuntimeError" in caplog.text


async def test_stop_twice_is_harmless(events):
    core = build_core(make_settings())
    await core.start()

    await core.stop()
    await core.stop()

    assert events.count("stop redis") == 1


def test_the_lifespan_starts_and_stops_with_the_app_and_runs_the_extra_steps(events):
    core = build_core(make_settings())
    disposed = []

    async def dispose():
        disposed.append(True)

    app = FastAPI(lifespan=core.make_lifespan(dispose))

    with TestClient(app):
        assert events == ["start http", "start redis", "start storage"]
        assert disposed == []

    assert events[-3:] == ["stop storage", "stop redis", "stop http"]
    assert disposed == [True]


def test_the_lifespan_cleans_up_even_when_a_shutdown_step_fails(events):
    core = build_core(make_settings())
    ran = []

    async def broken():
        raise RuntimeError("boom")

    async def after():
        ran.append("after")

    with TestClient(FastAPI(lifespan=core.make_lifespan(broken, after))):
        pass

    assert events[-1] == "stop http"
    assert ran == ["after"]  # a failing step does not skip the next ones
