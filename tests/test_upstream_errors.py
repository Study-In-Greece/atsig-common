import logging

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atsig_common.api_client.base import BaseAPI
from atsig_common.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    UpstreamError,
)
from atsig_common.fastapi_utils import setup_exception_handlers

INTERNAL_BODY = "Traceback: password=hunter2 at http://profiles:8000/applicants/1"


class Http:
    """An http manager whose client answers with `handler`."""

    def __init__(self, handler):
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def init_client(self):
        return None


def api_answering(status: int, body=None, content=None) -> BaseAPI:
    def handler(request):
        if content is not None:
            return httpx.Response(status, content=content)
        return httpx.Response(status, json=body if body is not None else {})

    return BaseAPI("http://profiles:8000", http_manager=Http(handler))


def api_raising(error: Exception) -> BaseAPI:
    def handler(request):
        raise error

    return BaseAPI("http://profiles:8000", http_manager=Http(handler))


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, NotFoundError), (409, ConflictError), (400, BadRequestError)],
)
async def test_errors_the_user_can_act_on_are_passed_on_with_their_detail(
    status, error
):
    api = api_answering(status, {"detail": "Applicant not found"})

    with pytest.raises(error) as raised:
        await api.get("/applicants/1")

    assert raised.value.message == "Applicant not found"


@pytest.mark.parametrize("status", [401, 403, 422, 500, 502, 503, 418])
async def test_every_other_answer_is_an_upstream_error_with_a_generic_message(status):
    api = api_answering(status, content=INTERNAL_BODY)

    with pytest.raises(UpstreamError) as raised:
        await api.get("/applicants/1")

    assert raised.value.status_code == 502
    assert "hunter2" not in raised.value.message
    assert "profiles" not in raised.value.message


async def test_the_status_of_the_other_service_goes_to_the_log_but_not_its_body(caplog):
    api = api_answering(403, content=INTERNAL_BODY)

    with caplog.at_level(logging.ERROR), pytest.raises(UpstreamError):
        await api.get("/applicants/1", params={"secret": "q"})

    assert "GET /applicants/1 answered 403" in caplog.text
    assert "hunter2" not in caplog.text
    assert "secret=q" not in caplog.text


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (httpx.ConnectError("refused at http://profiles:8000"), 502),
        (httpx.ReadTimeout("timed out"), 504),
        (httpx.ConnectTimeout("timed out"), 504),
    ],
)
async def test_network_errors_are_upstream_errors_without_the_internal_url(
    error, status, caplog
):
    api = api_raising(error)

    with caplog.at_level(logging.ERROR), pytest.raises(UpstreamError) as raised:
        await api.get("/applicants/1")

    assert raised.value.status_code == status
    assert "profiles:8000" not in raised.value.message
    assert "profiles:8000" not in caplog.text
    assert type(error).__name__ in caplog.text


def make_client(api: BaseAPI) -> TestClient:
    app = FastAPI()
    setup_exception_handlers(app)

    @app.get("/applicant")
    async def applicant():
        return await api.get("/applicants/1")

    return TestClient(app)


def test_a_refused_service_token_is_a_502_for_the_user_not_a_401():
    """The frontends log the user out on a 401. A problem between services must not."""
    response = make_client(api_answering(401, content=INTERNAL_BODY)).get("/applicant")

    assert response.status_code == 502
    assert response.json() == {
        "detail": "A service this one depends on did not answer correctly. "
        "Please try again later."
    }
    assert "hunter2" not in response.text


def test_a_timeout_is_a_504_and_a_404_still_reaches_the_user_as_it_was():
    timeout = make_client(api_raising(httpx.ReadTimeout("slow"))).get("/applicant")
    missing = make_client(api_answering(404, {"detail": "Applicant not found"})).get(
        "/applicant"
    )

    assert timeout.status_code == 504
    assert (missing.status_code, missing.json()) == (
        404,
        {"detail": "Applicant not found"},
    )
