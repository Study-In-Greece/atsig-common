import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from atsig_common.middleware.body_limit import MultipartBodyLimitMiddleware

LIMIT = 1000


async def upload(request):
    form = await request.form()
    return JSONResponse({"name": form["file"].filename})


async def echo(request):
    return JSONResponse({"size": len(await request.body())})


def make_client(**kwargs) -> TestClient:
    app = Starlette(
        routes=[
            Route("/upload", upload, methods=["POST"]),
            Route("/echo", echo, methods=["POST"]),
        ],
        middleware=[
            Middleware(MultipartBodyLimitMiddleware, max_body_size=LIMIT, **kwargs)
        ],
    )
    return TestClient(app)


def files(size: int):
    return {"file": ("a.pdf", b"x" * size, "application/pdf")}


def test_a_small_upload_goes_through():
    response = make_client().post("/upload", files=files(100))

    assert response.status_code == 200
    assert response.json() == {"name": "a.pdf"}


def test_a_big_upload_is_refused_with_the_message_of_the_size_check():
    response = make_client().post("/upload", files=files(LIMIT * 2))

    assert response.status_code == 400
    assert response.json() == {"detail": "Max file size reached"}


def test_a_big_upload_without_content_length_is_refused_while_streaming():
    boundary = "xyz"

    def body():
        yield f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a"\r\n\r\n'.encode()
        for _ in range(10):
            yield b"x" * 500
        yield f"\r\n--{boundary}--\r\n".encode()

    response = make_client().post(
        "/upload",
        content=body(),
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Max file size reached"


def test_status_and_detail_can_be_changed():
    response = make_client(status_code=413, detail="Too large").post(
        "/upload", files=files(LIMIT * 2)
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Too large"}


@pytest.mark.parametrize("content_type", ["application/json", "text/plain"])
def test_other_content_types_are_not_limited(content_type):
    response = make_client().post(
        "/echo", content=b"x" * (LIMIT * 3), headers={"content-type": content_type}
    )

    assert response.status_code == 200
    assert response.json() == {"size": LIMIT * 3}
