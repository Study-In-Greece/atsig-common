import httpx
import pytest

from atsig_common.api_client.base import BaseAPI
from atsig_common.api_client.clients.uni_api import UniAPI


class FakeHttpManager:
    """Replaces HttpClientManager: every request is answered by `handler`."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"ok": True})

    async def init_client(self):
        return None


@pytest.fixture
def http():
    return FakeHttpManager()


@pytest.mark.parametrize(
    "value", ["../secretaries/1", "a/b", "x?admin=1", "x#y", "a b"]
)
def test_path_segment_escapes_everything_with_a_meaning_in_a_url(value):
    segment = BaseAPI.path_segment(value)

    assert "/" not in segment
    assert "?" not in segment
    assert "#" not in segment
    assert " " not in segment


async def test_uni_api_department_id_is_escaped_too(http):
    await UniAPI("http://uni", http).get_department("1/../2")

    assert http.requests[0].url.raw_path.decode() == "/departments/1%2F..%2F2"


async def test_without_an_http_manager_the_shared_client_is_used(monkeypatch):
    from atsig_common.api_client.http_manager import HttpClientManager

    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(
        HttpClientManager,
        "client",
        httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )

    # http_manager=None used to fail with an AttributeError (None.client)
    assert await BaseAPI("http://svc").get("/ping") == {"ok": True}
    assert seen == ["/ping"]
