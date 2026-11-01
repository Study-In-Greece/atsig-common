import httpx
import pytest

from atsig_common.api_client.base import BaseAPI
from atsig_common.api_client.clients.uni_api import UniAPI
from atsig_common.api_client.clients.users_api import UsersAPI


class FakeTokenManager:
    def get_token(self):
        return "service-token"


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


@pytest.fixture
def users_api(http):
    return UsersAPI("http://profiles", FakeTokenManager(), http)


@pytest.mark.parametrize(
    "value", ["../secretaries/1", "a/b", "x?admin=1", "x#y", "a b"]
)
def test_path_segment_escapes_everything_with_a_meaning_in_a_url(value):
    segment = BaseAPI.path_segment(value)

    assert "/" not in segment
    assert "?" not in segment
    assert "#" not in segment
    assert " " not in segment


async def test_a_valid_uuid_gives_the_same_url_as_before(http, users_api):
    uuid = "3f1c9a52-8d2e-4c1b-9a77-0d6f3b1e2a44"

    await users_api.get_applicant(uuid)
    await users_api.get_applicant_profile(uuid)
    await users_api.get_applicant_media_url(uuid, "applicants/x/cv/a.pdf")

    assert [r.url.path for r in http.requests] == [
        f"/applicants/{uuid}",
        f"/applicants/{uuid}/complete",
        f"/applicants/{uuid}/media-url",
    ]
    assert http.requests[2].url.params["key"] == "applicants/x/cv/a.pdf"


async def test_an_id_cannot_reach_another_endpoint(http, users_api):
    await users_api.get_applicant("../agents/1")
    await users_api.get_secretary("1/../../users")
    await users_api.get_agent("1?x=y")

    paths = [r.url.raw_path.decode() for r in http.requests]
    assert paths == [
        "/applicants/..%2Fagents%2F1",
        "/secretaries/1%2F..%2F..%2Fusers",
        "/agents/1%3Fx%3Dy",
    ]
    assert all(r.url.query == b"" for r in http.requests)


async def test_uni_api_department_id_is_escaped_too(http):
    await UniAPI("http://uni", http).get_department("1/../2")

    assert http.requests[0].url.raw_path.decode() == "/departments/1%2F..%2F2"
