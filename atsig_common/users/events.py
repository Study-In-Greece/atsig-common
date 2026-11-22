"""
The `user_events` sync event for EVERY change of the user table, not only for the
changes that go through `UserService`.

    tracker = make_user_event_tracker(User, async_session, producer)
    tracker.attach(async_session)            # once, in main.py of the web process
    UserService(..., emit_sync_events=False)  # the tracker sends it now

A user written by a seeder, a command or a consumer reaches the stream too. The event is
built after the commit, from the row, with a session of its own, and sent with
`emit_safe`. The DELETE event is NOT sent from here: `UserService.delete_user` sends it
after the account was removed from Keycloak, and the tracker must not send it earlier. A
lost event (the process stops between the commit and the send) is repaired by the resync
of the service that owns the users.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from sqlalchemy import select

from ..events import Actions, Streams
from ..events.tracking import ChangeTracker, TrackedChange, spawn_background
from ..redis.producer import EventProducer
from .service import _user_sync_payload

logger = logging.getLogger("user-events")

KIND = "user"


async def publish_user_changes(
    changes: list[TrackedChange],
    *,
    user_model: type,
    session_factory: Callable[[], AbstractAsyncContextManager[Any]],
    producer: EventProducer,
) -> None:
    """Sends a sync event for each user that was created or changed (never raises)."""
    try:
        uuids = [change.pk for change in changes if not change.deleted]
        if not uuids:
            return
        async with session_factory() as session:
            users = (
                (
                    await session.execute(
                        select(user_model).where(user_model.uuid.in_(uuids))
                    )
                )
                .scalars()
                .all()
            )
        for user in users:
            await producer.emit_safe(
                stream_name=Streams.USERS,
                action=Actions.SYNC,
                payload=_user_sync_payload(user),
            )
    except Exception as e:
        # Ids and the type only: a user is personal data
        logger.error(
            "Could not publish the events of %d user(s): %s",
            len(changes),
            type(e).__name__,
        )


def make_user_event_tracker(
    user_model: type,
    session_factory: Callable[[], AbstractAsyncContextManager[Any]],
    producer: EventProducer,
) -> ChangeTracker:
    """A `ChangeTracker` of the user model that sends the sync events. Call `attach`."""

    def on_commit(changes: list[TrackedChange]) -> None:
        spawn_background(
            publish_user_changes(
                changes,
                user_model=user_model,
                session_factory=session_factory,
                producer=producer,
            )
        )

    return ChangeTracker({user_model: KIND}, on_commit)
