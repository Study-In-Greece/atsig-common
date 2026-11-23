"""
A consumer that keeps a local copy of a stream up to date: it validates an event with
its Pydantic model, applies it with a `Handler` inside one transaction, and tells
whether anything changed.

The statistics-api and the programmes-api (uni snapshots) each had their own copy of
this. A service writes a `Handler` per stream; the consumer, the retries, the DLQ and the
logs are the same everywhere.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, ClassVar

from pydantic import ValidationError

from ..events.schemas import Actions, EventPayload, validation_problems
from ..exceptions import NonRetryableError
from .consumer import BaseRedisConsumer, ConsumerOutcome, consumer_name_from_hostname
from .manager import RedisManager

logger = logging.getLogger("atsig_common.redis.handler_consumer")


def validate_event(
    model: type[EventPayload],
    message_id: str,
    payload: dict[str, Any],
    stream_name: str,
) -> Any:
    """
    Validates the payload of an event with its model. An invalid payload cannot be fixed
    by a retry: it raises `NonRetryableError` (the entry goes to the DLQ) with a message
    that names the fields and the error types only, never the values. Keys the model
    does not know are ignored, with a warning that names them.
    """
    try:
        event = model.model_validate(payload)
    except ValidationError as ve:
        problems = validation_problems(ve)
        logger.error(f"Schema validation failed for message {message_id}: {problems}")
        raise NonRetryableError(f"Invalid payload schema: {problems}") from None

    unexpected = model.unexpected_keys(payload)
    if unexpected:
        logger.warning(
            f"Ignored unexpected keys {[key[:50] for key in unexpected[:10]]} "
            f"in message {message_id} of '{stream_name}'"
        )
    return event


def _subject_id(event: Any) -> Any:
    """The id to write in the logs: `id`, or `uuid` for the user events."""
    value = getattr(event, "id", None)
    return value if value is not None else getattr(event, "uuid", "?")


class Handler:
    """
    What a service does with the events of ONE stream. `sync` and `delete` receive the
    validated event and the open session; they return True when they changed something
    and False when the event was stale or repeated. The consumer commits.
    """

    stream: ClassVar[str]
    name: ClassVar[str]  # short name: consumer name and logs
    sync_event: ClassVar[type[EventPayload]]
    delete_event: ClassVar[type[EventPayload] | None] = None

    async def sync(self, session: Any, event: Any) -> bool:
        raise NotImplementedError

    async def delete(self, session: Any, event: Any) -> bool:
        raise NotImplementedError


class HandlerConsumer(BaseRedisConsumer):
    """Validates an event with the model of the handler and applies it with it."""

    def __init__(
        self,
        redis_manager: RedisManager,
        handler: Handler,
        group_name: str,
        session_factory: Callable[[], AbstractAsyncContextManager[Any]],
        **kwargs: Any,
    ):
        kwargs.setdefault("consumer_name", consumer_name_from_hostname(handler.name))
        super().__init__(
            redis_manager=redis_manager,
            stream_name=handler.stream,
            group_name=group_name,
            **kwargs,
        )
        self.handler = handler
        self.session_factory = session_factory

    async def process_message(
        self, message_id: str, action: str, payload: dict[str, Any]
    ) -> ConsumerOutcome:
        handler = self.handler
        if action == Actions.SYNC:
            event = validate_event(
                handler.sync_event, message_id, payload, self.stream_name
            )
        elif action == Actions.DELETE and handler.delete_event is not None:
            event = validate_event(
                handler.delete_event, message_id, payload, self.stream_name
            )
        else:
            logger.warning(
                f"Unknown action '{action}' for message {message_id}. Skipping."
            )
            return ConsumerOutcome.ignored

        async with self.session_factory() as session:
            try:
                if action == Actions.SYNC:
                    applied = await handler.sync(session, event)
                else:
                    applied = await handler.delete(session, event)
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(
                    f"Transaction failed for {self.stream_name} "
                    f"{_subject_id(event)}: {type(e).__name__}"
                )
                raise  # Retry / DLQ mechanics of the base consumer

        subject = f"{self.stream_name} {_subject_id(event)} (Msg: {message_id})"
        if applied:
            logger.info(f"Applied '{action}' of {subject}")
            return ConsumerOutcome.applied
        logger.info(f"Skipped stale '{action}' of {subject}")
        return ConsumerOutcome.ignored
