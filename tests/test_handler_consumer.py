from contextlib import asynccontextmanager

import pytest

from atsig_common.events import Actions, EventPayload
from atsig_common.exceptions import NonRetryableError
from atsig_common.redis.consumer import ConsumerOutcome
from atsig_common.redis.handler_consumer import Handler, HandlerConsumer, validate_event


class ThingEvent(EventPayload):
    id: int
    version: int


class ThingDelete(EventPayload):
    id: int
    version: int


class FakeSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class ThingHandler(Handler):
    stream = "things"
    name = "thing"
    sync_event = ThingEvent
    delete_event = ThingDelete

    def __init__(self, result=True, fail=False):
        self.result = result
        self.fail = fail
        self.seen = []

    async def sync(self, session, event):
        if self.fail:
            raise RuntimeError("db is down")
        self.seen.append(("sync", event.id))
        return self.result

    async def delete(self, session, event):
        self.seen.append(("delete", event.id))
        return self.result


def make(handler, sessions):
    @asynccontextmanager
    async def factory():
        session = FakeSession()
        sessions.append(session)
        yield session

    return HandlerConsumer(None, handler, "group", factory)


async def test_sync_is_applied_and_committed():
    sessions = []
    consumer = make(ThingHandler(), sessions)

    outcome = await consumer.process_message(
        "1-0", Actions.SYNC, {"id": 7, "version": 2}
    )

    assert outcome == ConsumerOutcome.applied
    assert sessions[0].committed
    assert consumer.handler.seen == [("sync", 7)]


async def test_stale_event_is_ignored():
    consumer = make(ThingHandler(result=False), [])

    outcome = await consumer.process_message(
        "1-0", Actions.SYNC, {"id": 7, "version": 1}
    )

    assert outcome == ConsumerOutcome.ignored


async def test_delete_uses_the_delete_model():
    consumer = make(ThingHandler(), [])

    await consumer.process_message("1-0", Actions.DELETE, {"id": 7, "version": 3})

    assert consumer.handler.seen == [("delete", 7)]


async def test_unknown_action_is_ignored():
    consumer = make(ThingHandler(), [])

    outcome = await consumer.process_message("1-0", "weird", {})

    assert outcome == ConsumerOutcome.ignored


async def test_invalid_payload_is_non_retryable_and_names_no_values():
    consumer = make(ThingHandler(), [])

    with pytest.raises(NonRetryableError) as info:
        await consumer.process_message("1-0", Actions.SYNC, {"id": "secret-value"})

    assert "secret-value" not in str(info.value)


async def test_a_failing_handler_rolls_back_and_raises():
    sessions = []
    consumer = make(ThingHandler(fail=True), sessions)

    with pytest.raises(RuntimeError):
        await consumer.process_message("1-0", Actions.SYNC, {"id": 7, "version": 2})

    assert sessions[0].rolled_back
    assert not sessions[0].committed


def test_consumer_name_comes_from_the_handler_and_the_hostname():
    consumer = make(ThingHandler(), [])

    assert consumer.consumer_name.startswith("thing_")
    assert consumer.stream_name == "things"


def test_validate_event_ignores_unknown_keys():
    event = validate_event(
        ThingEvent, "1-0", {"id": 1, "version": 1, "extra": 1}, "things"
    )

    assert event.id == 1
