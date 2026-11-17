"""
Collects the rows a session changed and hands them over AFTER the commit.

A producer that sends an event for every change of a model used to call "notify" at each
place that changes the model, and a new place that forgot the call sent nothing. The
`ChangeTracker` listens to the session instead: after each flush it remembers the new,
modified and deleted rows of the tracked models, a rollback forgets them, and a commit
passes them to `on_commit`. What `on_commit` does (build the event, send it) is up to the
service: it runs in the event loop, so it starts a task with `spawn_background`, reads
the rows again with a session of its own and sends with `producer.emit_safe`.

Needs the `db` extra (SQLAlchemy). It is NOT imported by `atsig_common.events`.

Limits to know:
- A Core `update()` / `delete()` never reaches the flush, so it is invisible here: the
  service calls `tracker.track(session, Model, ids)` after it (and bumps the `version`
  column itself, because `version_id_col` only counts ORM updates).
- Listeners are attached to the class of the sync session. With the default
  `AsyncSession` that is SQLAlchemy's `Session` for the whole process: every session
  reaches the handlers, which ignore the models they do not track.
- A lost event (the process stops between the commit and the send) is not retried: the
  service keeps a resync command for that.
"""

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, NamedTuple

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from ..logger.config import get_logger

logger = get_logger("atsig_common.events.tracking")

_INFO_KEY = "atsig_common.change_tracker"

# Strong references: the event loop only keeps weak ones to a task.
_background_tasks: set[asyncio.Task] = set()


class TrackedChange(NamedTuple):
    """One changed row. `version` is the value of the model's version attribute when
    it has one (for a deleted row: the last stored version, not +1)."""

    kind: str
    pk: Any
    deleted: bool
    version: int | None


def spawn_background(coro: Coroutine[Any, Any, Any]) -> asyncio.Task | None:
    """
    Starts `coro` as a task that is not awaited, keeps it alive until it ends, and logs
    (the type of) an exception it ends with. Without a running loop the coroutine is
    closed and None is returned: a sync session has nowhere to run it.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        logger.error("spawn_background without a running event loop; dropped")
        return None
    task = loop.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_task_done)
    return task


def _background_task_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Background task failed: %s", type(exc).__name__)


def _resolve_session_class(target: Any) -> Any:
    """async_sessionmaker -> its AsyncSession class -> the sync session class."""
    class_ = getattr(target, "class_", None)
    if class_ is not None:
        target = class_
    return getattr(target, "sync_session_class", target)


class ChangeTracker:
    """
    Args:
        models: the tracked model classes and the `kind` each one is reported as.
        on_commit: called (sync, once per commit with changes) with the list of
            `TrackedChange`, after the outermost transaction committed. It must not
            raise (an error is logged and swallowed: the commit already happened).
        version_attr: name of the version attribute of the models, if they have one.
    """

    def __init__(
        self,
        models: Mapping[type, str],
        on_commit: Callable[[list[TrackedChange]], None],
        version_attr: str = "version",
    ):
        self._models = dict(models)
        self._on_commit = on_commit
        self._version_attr = version_attr
        self._key = f"{_INFO_KEY}.{id(self)}"
        self._attached: list[tuple[Any, str, Callable]] = []

    # -- wiring ---------------------------------------------------------------------

    def attach(self, target: Any) -> None:
        """
        Starts listening. `target` is an `async_sessionmaker`, an `AsyncSession` class,
        or a sync `Session` class / `sessionmaker`.
        """
        session_class = _resolve_session_class(target)
        for name, handler in (
            ("after_flush", self._after_flush),
            ("after_commit", self._after_commit),
            ("after_transaction_end", self._after_transaction_end),
        ):
            event.listen(session_class, name, handler)
            self._attached.append((session_class, name, handler))

    def detach(self) -> None:
        for session_class, name, handler in self._attached:
            if event.contains(session_class, name, handler):
                event.remove(session_class, name, handler)
        self._attached.clear()

    # -- explicit tracking ----------------------------------------------------------

    def track(
        self,
        session: Any,
        model: type,
        ids: list[Any],
        *,
        deleted: bool = False,
        version: int | None = None,
    ) -> None:
        """
        Records rows changed outside the flush (a Core `update()` / `delete()`). Call
        it in the same transaction: a rollback forgets it, the commit sends it.
        """
        kind = self._models[model]
        pending = self._pending(_sync(session))
        for pk in ids:
            pending[(kind, pk)] = TrackedChange(kind, pk, deleted, version)

    # -- listeners ------------------------------------------------------------------

    def _pending(self, session: Session) -> dict[tuple[str, Any], TrackedChange]:
        return session.info.setdefault(self._key, {})

    def _after_flush(self, session: Session, flush_context: Any) -> None:
        pending = None
        for instances, deleted in (
            (session.new, False),
            (session.dirty, False),
            (session.deleted, True),
        ):
            for obj in instances:
                kind = self._models.get(type(obj))
                if kind is None:
                    continue
                if (
                    not deleted
                    and obj in session.dirty
                    and not session.is_modified(obj, include_collections=False)
                ):
                    continue
                if pending is None:
                    pending = self._pending(session)
                state = inspect(obj)
                pk = state.identity[0] if state.identity else None
                if pk is None:
                    mapper_pk = state.mapper.primary_key_from_instance(obj)
                    pk = mapper_pk[0]
                pending[(kind, pk)] = TrackedChange(
                    kind,
                    pk,
                    deleted,
                    getattr(obj, self._version_attr, None),
                )

    def _after_commit(self, session: Session) -> None:
        changes = session.info.pop(self._key, None)
        if not changes:
            return
        try:
            self._on_commit(list(changes.values()))
        except Exception as e:
            # The commit happened; a failing callback must not turn it into an error.
            logger.error("ChangeTracker on_commit failed: %s", type(e).__name__)

    def _after_transaction_end(self, session: Session, transaction: Any) -> None:
        # Runs after `after_commit`, which already took the changes. What is left belongs
        # to a rollback or a close. `after_rollback` can not be used: it also fires for a
        # savepoint, and a rolled back savepoint keeps what the outer transaction
        # collected (it may send an event for a row that did not change: the builder
        # reads the database).
        if transaction.parent is None:
            session.info.pop(self._key, None)


def _sync(session: Any) -> Session:
    return getattr(session, "sync_session", session)
