from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from atsig_common.fastapi_utils import setup_exception_handlers


class Item(BaseModel):
    name: str = Field(min_length=3)
    score: float = Field(ge=0, le=10)


def make_client() -> TestClient:
    app = FastAPI()
    setup_exception_handlers(app)

    @app.post("/items")
    async def create(item: Item):
        return item

    return TestClient(app)


def test_validation_error_keeps_loc_and_msg_and_drops_the_input():
    response = make_client().post("/items", json={"name": "ab", "score": 99})

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert {tuple(e["loc"]) for e in errors} == {("body", "name"), ("body", "score")}
    assert all(set(e) == {"type", "loc", "msg"} for e in errors)
    assert "99" not in response.text


def test_nan_and_infinity_give_422_instead_of_500():
    client = make_client()

    # Python's json module accepts NaN/Infinity, so a client can send them
    for body in ('{"name": "abc", "score": NaN}', '{"name": "abc", "score": Infinity}'):
        response = client.post(
            "/items", content=body, headers={"content-type": "application/json"}
        )
        assert response.status_code == 422, body
        assert response.json()["detail"][0]["loc"] == ["body", "score"]
