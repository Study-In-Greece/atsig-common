from contextlib import asynccontextmanager

from atsig_common.events import Actions, Streams
from atsig_common.events.tracking import TrackedChange
from atsig_common.users import publish_user_changes


class FakeUser:
    def __init__(self, uuid, email="a@b.gr", first_name="A", last_name="B"):
        self.uuid = uuid
        self.email = email
        self.first_name = first_name
        self.last_name = last_name


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, statement):
        return FakeResult(self.rows)


class Producer:
    def __init__(self):
        self.events = []

    async def emit_safe(self, **kwargs):
        self.events.append(kwargs)


def factory(rows, boom=False):
    @asynccontextmanager
    async def session_factory():
        if boom:
            raise RuntimeError("db is down")
        yield FakeSession(rows)

    return session_factory


class UserModel:
    uuid = type("Col", (), {"in_": staticmethod(lambda ids: True)})()


async def test_a_sync_event_for_every_changed_user(monkeypatch):
    import atsig_common.users.events as events_module

    monkeypatch.setattr(events_module, "select", lambda model: _Select())
    producer = Producer()
    changes = [
        TrackedChange("user", "u1", False, None),
        TrackedChange("user", "u2", False, None),
    ]

    await publish_user_changes(
        changes,
        user_model=UserModel,
        session_factory=factory([FakeUser("u1"), FakeUser("u2", email="c@d.gr")]),
        producer=producer,
    )

    assert [e["stream_name"] for e in producer.events] == [Streams.USERS] * 2
    assert {e["action"] for e in producer.events} == {Actions.SYNC}
    assert {e["payload"]["uuid"] for e in producer.events} == {"u1", "u2"}


async def test_a_deleted_user_sends_nothing_from_the_tracker():
    producer = Producer()

    await publish_user_changes(
        [TrackedChange("user", "u1", True, None)],
        user_model=UserModel,
        session_factory=factory([]),
        producer=producer,
    )

    assert producer.events == []


async def test_a_failure_is_logged_not_raised():
    producer = Producer()

    await publish_user_changes(
        [TrackedChange("user", "u1", False, None)],
        user_model=UserModel,
        session_factory=factory([], boom=True),
        producer=producer,
    )

    assert producer.events == []


class _Select:
    def where(self, condition):
        return self
