import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from redis.exceptions import ResponseError

from atsig_common.admin.resync import ResyncJob, make_resync_router
from atsig_common.admin.streams import StreamSpec, make_streams_router
from atsig_common.events import Actions
from atsig_common.fastapi_utils import setup_exception_handlers
from atsig_common.redis.consumer import BaseRedisConsumer, ConsumerOutcome


class KV:
    """A tiny in-memory Redis for the admin routers (strings, hashes, streams)."""

    def __init__(self):
        self.redis = self
        self.hashes: dict[str, dict] = {}
        self.keys: dict[str, str] = {}
        self.streams: dict[str, list[tuple[str, dict]]] = {}
        self.groups: dict[str, list[dict]] = {}

    async def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def expire(self, key, seconds):
        pass

    async def delete(self, key):
        self.keys.pop(key, None)

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True

    async def xrange(self, name, min="-", max="+"):
        entries = self.streams.get(name, [])
        if min != "-":
            return [e for e in entries if e[0] == min]
        return list(entries)

    async def xdel(self, name, *ids):
        self.streams[name] = [e for e in self.streams.get(name, []) if e[0] not in ids]

    async def xlen(self, name):
        if name not in self.streams:
            raise ResponseError("no such key")
        return len(self.streams[name])

    async def xinfo_groups(self, name):
        if name not in self.streams:
            raise ResponseError("no such key")
        return self.groups.get(name, [])


def dlq_entry(message_id, action=Actions.SYNC, data=None, error="boom"):
    return (
        message_id,
        {
            "original_message_id": "9-0",
            "payload": json.dumps({"action": action, "data": json.dumps(data or {})}),
            "error": error,
            "consumer_group": "g",
        },
    )


class Replayer(BaseRedisConsumer):
    def __init__(self, result=ConsumerOutcome.applied, fail=False):
        self.result = result
        self.fail = fail
        self.got = None

    async def process_message(self, message_id, action, payload):
        if self.fail:
            raise ValueError("still bad")
        self.got = (message_id, action, payload)
        return self.result


@pytest.fixture
def kv():
    return KV()


def streams_client(kv, **kwargs):
    streams = {
        "things": StreamSpec("g", build_consumer=lambda: kwargs.get("consumer")),
        "exports": StreamSpec("g", not_replayable="retry it from the screen"),
    }
    router = make_streams_router(streams=streams, get_redis=lambda: kv, dependencies=[])
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(router, prefix="/admin/streams")
    return TestClient(app, raise_server_exceptions=False)


def test_overview_shows_every_stream_with_its_group(kv):
    kv.streams["things"] = [("1-0", {})]
    kv.streams["things_dlq"] = [dlq_entry("5-0")]
    kv.groups["things"] = [
        {"name": "g", "consumers": 2, "pending": 3, "lag": 4},
        {"name": "other", "consumers": 9, "pending": 9, "lag": 9},
    ]

    rows = streams_client(kv).get("/admin/streams/").json()

    things = next(r for r in rows if r["stream"] == "things")
    assert things == {
        "stream": "things",
        "group": "g",
        "length": 1,
        "dlq_length": 1,
        "consumers": 2,
        "pending": 3,
        "lag": 4,
        "replayable": True,
    }
    exports = next(r for r in rows if r["stream"] == "exports")
    assert exports["length"] == 0 and exports["replayable"] is False


def test_list_reads_the_dlq_and_flags_an_unreadable_entry(kv):
    kv.streams["things_dlq"] = [
        dlq_entry("5-0", data={"id": 1}),
        ("6-0", {"payload": "not json", "error": "x"}),
    ]

    rows = streams_client(kv).get("/admin/streams/things").json()

    assert rows[0]["action"] == "sync" and rows[0]["payload"] == {"id": 1}
    assert rows[1]["action"] == "unreadable"


def test_unknown_stream_is_a_422(kv):
    assert streams_client(kv).get("/admin/streams/nope").status_code == 422


def test_replay_runs_the_event_and_removes_the_entry(kv):
    kv.streams["things_dlq"] = [dlq_entry("5-0", data={"id": 1})]
    consumer = Replayer(result=ConsumerOutcome.ignored)

    response = streams_client(kv, consumer=consumer).post(
        "/admin/streams/things/5-0/replay"
    )

    assert response.json() == {
        "status": "replayed",
        "outcome": "ignored",
        "message_id": "5-0",
    }
    assert consumer.got == ("9-0", "sync", {"id": 1})
    assert kv.streams["things_dlq"] == []


def test_a_failing_replay_keeps_the_entry(kv):
    kv.streams["things_dlq"] = [dlq_entry("5-0")]

    response = streams_client(kv, consumer=Replayer(fail=True)).post(
        "/admin/streams/things/5-0/replay"
    )

    assert response.status_code == 400
    assert len(kv.streams["things_dlq"]) == 1


def test_a_stream_that_is_not_replayable_answers_400(kv):
    kv.streams["exports_dlq"] = [dlq_entry("5-0")]

    response = streams_client(kv).post("/admin/streams/exports/5-0/replay")

    assert response.status_code == 400
    assert "retry it from the screen" in response.text


def test_replay_of_an_unreadable_entry_is_400_and_discard_works(kv):
    kv.streams["things_dlq"] = [("6-0", {"payload": "not json"})]
    client = streams_client(kv, consumer=Replayer())

    assert client.post("/admin/streams/things/6-0/replay").status_code == 400
    assert client.delete("/admin/streams/things/6-0").json() == {
        "status": "discarded",
        "message_id": "6-0",
    }
    assert kv.streams["things_dlq"] == []


def test_a_missing_entry_is_404(kv):
    kv.streams["things_dlq"] = []

    assert streams_client(kv).delete("/admin/streams/things/1-0").status_code == 404


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    programme_id: int | None = None


def resync_client(kv, run):
    jobs = [
        ResyncJob("stats", "all of it", run, Params),
        ResyncJob("plain", "no params", run),
    ]
    router = make_resync_router(jobs=jobs, get_redis=lambda: kv, dependencies=[])
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(router, prefix="/admin/resync")
    return TestClient(app, raise_server_exceptions=False)


def test_resync_lists_jobs_and_starts_one():
    kv = KV()
    seen = []

    async def run(values):
        seen.append(values)
        return 12

    with resync_client(kv, run) as client:
        jobs = client.get("/admin/resync/").json()
        assert [j["name"] for j in jobs] == ["stats", "plain"]
        assert jobs[0]["state"] == "idle" and jobs[0]["params"] is not None

        started = client.post("/admin/resync/stats", json={"programme_id": 3})
        assert started.status_code == 202
        assert started.json()["state"] == "running"

        status = client.get("/admin/resync/stats").json()

    assert seen == [{"programme_id": 3}]
    assert status["state"] in ("running", "ok")


async def test_job_runner_records_the_count_and_frees_the_lock():
    from atsig_common.admin.resync import _lock_key, _run_job

    kv = KV()
    kv.keys[_lock_key("stats")] = "1"

    async def run(values):
        return 5

    await _run_job(kv, ResyncJob("stats", "d", run), {})

    assert kv.hashes["resync:stats"]["state"] == "ok"
    assert kv.hashes["resync:stats"]["count"] == "5"
    assert _lock_key("stats") not in kv.keys


async def test_job_runner_records_only_the_type_of_an_error():
    from atsig_common.admin.resync import _run_job

    kv = KV()

    async def run(values):
        raise RuntimeError("secret value inside")

    await _run_job(kv, ResyncJob("stats", "d", run), {})

    assert kv.hashes["resync:stats"]["state"] == "error"
    assert kv.hashes["resync:stats"]["error"] == "RuntimeError"
    assert "secret" not in json.dumps(kv.hashes)


def test_a_second_start_while_running_is_409():
    kv = KV()
    release = asyncio.Event()

    async def run(values):
        await release.wait()
        return 1

    with resync_client(kv, run) as client:
        assert client.post("/admin/resync/plain").status_code == 202
        assert client.post("/admin/resync/plain").status_code == 409


def test_bad_parameters_and_unknown_jobs():
    async def run(values):
        return 0

    with resync_client(KV(), run) as client:
        assert client.post("/admin/resync/stats", json={"nope": 1}).status_code == 400
        assert client.post("/admin/resync/plain", json={"x": 1}).status_code == 400
        assert client.post("/admin/resync/missing").status_code == 404
