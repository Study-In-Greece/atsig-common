import asyncio

import pytest
from sqlalchemy import Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from atsig_common.events import tracking
from atsig_common.events.tracking import ChangeTracker, TrackedChange, spawn_background


class Base(DeclarativeBase):
    pass


class Thing(Base):
    __tablename__ = "thing"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class Other(Base):
    __tablename__ = "other"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)


class MySession(Session):
    """Own class, so the listeners of a test never reach another test."""


@pytest.fixture
def env():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    batches: list[list[TrackedChange]] = []
    tracker = ChangeTracker({Thing: "thing"}, batches.append)
    tracker.attach(MySession)
    yield MySession(engine, expire_on_commit=False), batches, tracker
    tracker.detach()


def test_commit_hands_over_new_modified_and_deleted(env):
    session, batches, _ = env
    a, b = Thing(name="a"), Thing(name="b")
    session.add_all([a, b])
    session.commit()
    assert [c.kind for c in batches[0]] == ["thing", "thing"]
    assert {c.pk for c in batches[0]} == {a.id, b.id}
    assert not any(c.deleted for c in batches[0])

    a.name = "a2"
    session.delete(b)
    session.commit()
    by_pk = {c.pk: c for c in batches[1]}
    assert by_pk[a.id].deleted is False
    assert by_pk[a.id].version == 2
    assert by_pk[b.id].deleted is True
    assert by_pk[b.id].version == 1  # the last stored one, the service adds 1


def test_nothing_is_sent_before_the_commit(env):
    session, batches, _ = env
    session.add(Thing(name="a"))
    session.flush()
    assert batches == []
    session.commit()
    assert len(batches) == 1


def test_rollback_forgets_the_changes(env):
    session, batches, _ = env
    session.add(Thing(name="a"))
    session.flush()
    session.rollback()
    session.commit()
    assert batches == []


def test_untouched_dirty_row_is_ignored(env):
    session, batches, _ = env
    thing = Thing(name="a")
    session.add(thing)
    session.commit()
    batches.clear()

    thing.name = "a"  # set to the same value: no net change
    session.commit()
    assert batches == []


def test_untracked_model_is_ignored(env):
    session, batches, _ = env
    session.add(Other(name="x"))
    session.commit()
    assert batches == []


def test_same_row_changed_twice_is_one_change(env):
    session, batches, _ = env
    thing = Thing(name="a")
    session.add(thing)
    session.flush()
    thing.name = "b"
    session.commit()
    assert len(batches) == 1
    assert len(batches[0]) == 1


def test_rolled_back_savepoint_keeps_the_outer_changes(env):
    session, batches, _ = env
    session.add(Thing(name="outer"))
    session.flush()
    nested = session.begin_nested()
    session.add(Thing(name="inner"))
    session.flush()
    nested.rollback()
    session.commit()
    assert len(batches) == 1
    # the outer row is there; the inner one may be too (the builder reads the database)
    assert any(c.pk == 1 for c in batches[0])


def test_track_records_rows_outside_the_flush(env):
    session, batches, tracker = env
    tracker.track(session, Thing, [5, 6])
    session.commit()
    assert {c.pk for c in batches[0]} == {5, 6}


def test_track_is_forgotten_on_rollback(env):
    session, batches, tracker = env
    session.connection()  # the transaction a real query would have begun
    tracker.track(session, Thing, [5])
    session.rollback()
    session.commit()
    assert batches == []


def test_callback_error_does_not_break_the_commit():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    def boom(changes):
        raise RuntimeError("secret detail")

    class S(Session):
        pass

    tracker = ChangeTracker({Thing: "thing"}, boom)
    tracker.attach(S)
    try:
        session = S(engine)
        session.add(Thing(name="a"))
        session.commit()  # does not raise
        assert session.query(Thing).count() == 1
    finally:
        tracker.detach()


def test_detach_stops_the_listening():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    batches = []

    class S(Session):
        pass

    tracker = ChangeTracker({Thing: "thing"}, batches.append)
    tracker.attach(S)
    tracker.detach()
    session = S(engine)
    session.add(Thing(name="a"))
    session.commit()
    assert batches == []


async def test_spawn_background_runs_and_releases_the_task():
    done = asyncio.Event()

    async def work():
        done.set()

    task = spawn_background(work())
    assert task in tracking._background_tasks
    await done.wait()
    await task
    await asyncio.sleep(0)
    assert task not in tracking._background_tasks


async def test_spawn_background_logs_only_the_exception_type(caplog):
    async def work():
        raise ValueError("private value")

    task = spawn_background(work())
    with pytest.raises(ValueError):
        await task
    await asyncio.sleep(0)
    assert "ValueError" in caplog.text
    assert "private value" not in caplog.text


def test_spawn_background_without_a_loop_drops_the_coroutine():
    async def work():
        pass

    assert spawn_background(work()) is None


def test_close_without_commit_forgets_the_changes(env):
    session, batches, _ = env
    session.add(Thing(name="a"))
    session.flush()
    session.close()
    session.commit()
    assert batches == []
