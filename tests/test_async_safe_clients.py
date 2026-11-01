import asyncio
import threading

import httpx
import pytest

from atsig_common.api_client.base import BaseAPI
from atsig_common.api_client.clients.users_api import UsersAPI
from atsig_common.auth.service_token import ServiceTokenManager
from atsig_common.email.client import AsyncEmailClient

MAIN_THREAD = threading.get_ident()


class FakeKeycloak:
    def __init__(self):
        self.calls = 0
        self.threads: list[int] = []

    def token(self, grant_type):
        self.calls += 1
        self.threads.append(threading.get_ident())
        import time

        time.sleep(0.05)  # a network call that blocks
        return {"access_token": f"token-{self.calls}", "expires_in": 300}


async def test_a_refresh_runs_off_the_event_loop_thread():
    keycloak = FakeKeycloak()

    token = await ServiceTokenManager(keycloak).aget_token()

    assert token == "token-1"
    assert keycloak.threads == [keycloak.threads[0]]
    assert keycloak.threads[0] != MAIN_THREAD


async def test_concurrent_requests_share_one_refresh():
    keycloak = FakeKeycloak()
    manager = ServiceTokenManager(keycloak)

    tokens = await asyncio.gather(*(manager.aget_token() for _ in range(8)))

    assert keycloak.calls == 1
    assert set(tokens) == {"token-1"}


async def test_a_fresh_token_is_reused_without_a_new_refresh():
    keycloak = FakeKeycloak()
    manager = ServiceTokenManager(keycloak)

    await manager.aget_token()
    await manager.aget_token()
    assert manager.get_token() == "token-1"  # the sync path shares the same cache

    assert keycloak.calls == 1


class Http:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request):
        self.requests.append(request)
        return httpx.Response(200, json={})

    async def init_client(self):
        return None


async def test_users_api_sends_the_service_token_without_blocking():
    http = Http()
    api = UsersAPI("http://profiles", ServiceTokenManager(FakeKeycloak()), http)

    await api.get_applicant("u1")

    assert http.requests[0].headers["Authorization"] == "Bearer token-1"


@pytest.mark.parametrize("is_async", [False, True])
async def test_base_api_accepts_a_sync_or_an_async_auth_hook(is_async):
    http = Http()

    class SyncApi(BaseAPI):
        def _get_auth_headers(self):
            return {"X-Key": "sync"}

    class AsyncApi(BaseAPI):
        async def _get_auth_headers(self):
            return {"X-Key": "async"}

    api = (AsyncApi if is_async else SyncApi)("http://svc", http_manager=http)
    await api.get("/x")

    assert http.requests[0].headers["X-Key"] == ("async" if is_async else "sync")


class FakeCelery:
    def __init__(self):
        self.sent = []

    def send_task(self, name, kwargs, queue):
        self.sent.append((name, queue, threading.get_ident()))
        return type("Task", (), {"id": "task-1"})()


async def test_async_email_variants_queue_the_task_in_a_thread():
    client = AsyncEmailClient("redis://localhost:6379/0")
    client.celery_app = FakeCelery()

    one = await client.asend_email("welcome", {"name": "Ada"}, recipient_email="a@x.gr")
    bulk = await client.asend_bulk_emails("news", {}, recipients=["a@x.gr"])

    assert (one, bulk) == ("task-1", "task-1")
    names = [sent[0] for sent in client.celery_app.sent]
    assert names == [client.config.TASK_SEND_HIGH, client.config.TASK_SEND_BULK]
    assert all(sent[2] != MAIN_THREAD for sent in client.celery_app.sent)
