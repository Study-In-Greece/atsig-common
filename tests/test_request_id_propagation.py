import json

import httpx
import pytest

from atsig_common.api_client.base import BaseAPI
from atsig_common.logger.context import request_id_var
from atsig_common.redis.consumer import BaseRedisConsumer
from atsig_common.redis.producer import EventProducer


class Http:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request):
        self.requests.append(request)
        return httpx.Response(200, json={})

    async def init_client(self):
        return None


@pytest.fixture
def http():
    return Http()


async def test_an_outgoing_call_carries_the_id_of_the_request(http):
    token = request_id_var.set("req-42")
    try:
        await BaseAPI("http://svc", http_manager=http).get("/x")
    finally:
        request_id_var.reset(token)

    assert http.requests[0].headers["X-Request-ID"] == "req-42"


async def test_without_a_request_there_is_no_header(http):
    await BaseAPI("http://svc", http_manager=http).get("/x")

    assert "X-Request-ID" not in http.requests[0].headers


async def test_the_caller_can_still_set_the_header_itself(http):
    token = request_id_var.set("req-42")
    try:
        await BaseAPI("http://svc", http_manager=http).get(
            "/x", headers={"X-Request-ID": "mine"}
        )
    finally:
        request_id_var.reset(token)

    assert http.requests[0].headers["X-Request-ID"] == "mine"


class Redis:
    def __init__(self):
        self.entries = []

    async def xadd(self, name, fields, **kwargs):
        self.entries.append(fields)
        return "1-0"


async def test_an_event_carries_the_request_id_in_meta_not_in_the_payload():
    redis = Redis()
    token = request_id_var.set("req-42")
    try:
        await EventProducer(redis).emit("events", "sync", {"id": 1})
    finally:
        request_id_var.reset(token)

    (entry,) = redis.entries
    assert json.loads(entry["data"]) == {"id": 1}
    assert json.loads(entry["meta"]) == {"request_id": "req-42"}


async def test_an_event_without_a_request_has_no_meta():
    redis = Redis()

    await EventProducer(redis).emit("events", "sync", {"id": 1})

    assert set(redis.entries[0]) == {"action", "data"}


class Spy(BaseRedisConsumer):
    def __init__(self, redis_manager):
        super().__init__(redis_manager, "events", "g", retry_delay=0)
        self.seen = []

    async def process_message(self, message_id, action, payload):
        self.seen.append(request_id_var.get())


def entry(**extra):
    return {"action": "sync", "data": "{}", **extra}


async def test_the_consumer_logs_under_the_id_of_the_producer(fake_redis):
    consumer = Spy(fake_redis)

    await consumer._handle_message(
        "9-0", entry(meta=json.dumps({"request_id": "req-42"}))
    )

    assert consumer.seen == ["req-42"]
    assert request_id_var.get() == "-"  # restored afterwards


@pytest.mark.parametrize(
    "meta",
    ["not json", json.dumps({"request_id": "bad id!"}), json.dumps(["x"]), "{}"],
)
async def test_a_bad_or_missing_meta_falls_back_to_the_entry_id(fake_redis, meta):
    consumer = Spy(fake_redis)

    await consumer._handle_message("9-0", entry(meta=meta))
    await consumer._handle_message("10-0", entry())

    assert consumer.seen == ["9-0", "10-0"]
    assert len(fake_redis.commands("xack")) == 2  # a bad meta never fails a message
