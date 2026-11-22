import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import APIRouter, params
from redis.exceptions import ResponseError

from atsig_common.events.schemas import Actions, dlq_name
from atsig_common.exceptions import BadRequestError, NotFoundError
from atsig_common.redis.consumer import BaseRedisConsumer, ConsumerOutcome
from atsig_common.redis.manager import RedisManager

from .schemas import (
    DLQDiscardRead,
    DLQEntryRead,
    DLQReplayRead,
    StreamOverviewRead,
)

logger = logging.getLogger("atsig_common.admin.streams")


@dataclass(frozen=True)
class StreamSpec:
    """
    A stream the service reads.

    Attributes:
        group: The consumer group of this service on the stream.
        build_consumer: Builds the consumer whose `process_message` replays an entry.
            It is built per request and never run as a loop.
        not_replayable: When set, replay answers 400 with this text (the entry can only
            be discarded; whatever it describes is retried somewhere else).
    """

    group: str
    build_consumer: Callable[[], BaseRedisConsumer] | None = None
    not_replayable: str | None = None

    @property
    def replayable(self) -> bool:
        return self.build_consumer is not None and self.not_replayable is None


class UnreadableEntry(Exception):
    """A DLQ entry that cannot be read back; the message says why."""


def _decode(value: Any) -> Any:
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _decode_fields(fields: dict) -> dict:
    try:
        return {_decode(k): _decode(v) for k, v in fields.items()}
    except Exception as e:
        raise UnreadableEntry("fields are not valid text") from e


def _parse_event(decoded: dict) -> tuple[str, dict]:
    """Returns (action, payload) of the event kept in the entry."""
    if "payload" not in decoded:
        raise UnreadableEntry("the payload field is missing")
    try:
        wrapper = json.loads(decoded["payload"])
    except (TypeError, ValueError) as e:
        raise UnreadableEntry("the payload field is not valid JSON") from e
    if not isinstance(wrapper, dict):
        raise UnreadableEntry("the payload field is not an object")

    data = wrapper.get("data", "{}")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError as e:
            raise UnreadableEntry("the event data is not valid JSON") from e
    if not isinstance(data, dict):
        raise UnreadableEntry("the event data is not an object")

    return str(wrapper.get("action") or ""), data


async def list_dlq_entries(redis: RedisManager, stream: str) -> list[DLQEntryRead]:
    entries = []
    for dlq_id, fields in await redis.xrange(dlq_name(stream)):
        dlq_message_id = _decode(dlq_id)
        decoded: dict = {}
        try:
            decoded = _decode_fields(fields)
            action, payload = _parse_event(decoded)
            error = decoded.get("error", "")
        except UnreadableEntry as e:
            # One bad entry must not hide the rest of the queue
            action, payload = Actions.UNREADABLE, {}
            error = f"Unreadable DLQ entry: {e}"
            original_error = str(decoded.get("error", ""))[:200]
            if original_error:
                error += f" (original error: {original_error})"
            logger.warning(
                f"Unreadable DLQ entry {dlq_message_id} on {dlq_name(stream)}: {e}"
            )
        entries.append(
            DLQEntryRead(
                dlq_message_id=dlq_message_id,
                original_message_id=str(decoded.get("original_message_id", "")),
                action=action,
                payload=payload,
                error=error,
                consumer_group=str(decoded.get("consumer_group", "")),
            )
        )
    return entries


async def _read_entry(redis: RedisManager, stream: str, dlq_message_id: str) -> dict:
    raw = await redis.xrange(dlq_name(stream), min=dlq_message_id, max=dlq_message_id)
    if not raw:
        raise NotFoundError(f"DLQ entry {dlq_message_id} not found")
    return raw[0][1]


async def replay_dlq_entry(
    redis: RedisManager, stream: str, spec: StreamSpec, dlq_message_id: str
) -> ConsumerOutcome:
    """
    Runs the event again and removes the entry. The result says whether the event
    changed anything or was ignored (e.g. a stale version): the entry goes in both
    cases, as the event has been handled.
    """
    if spec.not_replayable:
        raise BadRequestError(spec.not_replayable)
    if spec.build_consumer is None:
        raise BadRequestError("This stream cannot be replayed from here.")

    fields = await _read_entry(redis, stream, dlq_message_id)
    try:
        decoded = _decode_fields(fields)
        action, data = _parse_event(decoded)
    except UnreadableEntry as e:
        raise BadRequestError(
            f"The DLQ entry is unreadable ({e}) and cannot be replayed: discard it."
        ) from e
    original_id = decoded.get("original_message_id", dlq_message_id)

    consumer = spec.build_consumer()
    try:
        outcome = await consumer.process_message(original_id, action, data)
    except Exception as e:
        # The entry STAYS in the DLQ. A clear 400 for the admin, not a 500.
        logger.warning(
            f"Replay failed for DLQ entry {dlq_message_id} on {dlq_name(stream)}: "
            f"{type(e).__name__}"
        )
        raise BadRequestError(
            f"Replay failed - the payload is still invalid or the error persists: {e}"
        ) from e

    await redis.xdel(dlq_name(stream), dlq_message_id)
    outcome = outcome or ConsumerOutcome.applied
    logger.info(
        f"Replayed DLQ entry {dlq_message_id} from {dlq_name(stream)}: {outcome}"
    )
    return outcome


async def discard_dlq_entry(
    redis: RedisManager, stream: str, dlq_message_id: str
) -> None:
    await _read_entry(redis, stream, dlq_message_id)
    await redis.xdel(dlq_name(stream), dlq_message_id)
    logger.info(f"Discarded DLQ entry {dlq_message_id} from {dlq_name(stream)}")


async def _length(redis: RedisManager, name: str) -> int:
    try:
        return int(await redis.xlen(name))
    except Exception:
        return 0  # the stream does not exist until something is written to it


async def stream_overview(
    redis: RedisManager, stream: str, spec: StreamSpec
) -> StreamOverviewRead:
    consumers = pending = 0
    lag = None
    try:
        for group in await redis.xinfo_groups(stream):
            if _decode(group.get("name")) == spec.group:
                consumers = int(group.get("consumers") or 0)
                pending = int(group.get("pending") or 0)
                raw_lag = group.get("lag")
                lag = int(raw_lag) if raw_lag is not None else None
    except ResponseError:
        pass  # no such stream yet
    return StreamOverviewRead(
        stream=stream,
        group=spec.group,
        length=await _length(redis, stream),
        dlq_length=await _length(redis, dlq_name(stream)),
        consumers=consumers,
        pending=pending,
        lag=lag,
        replayable=spec.replayable,
    )


def make_streams_router(
    *,
    streams: dict[str, StreamSpec],
    get_redis: Callable[[], RedisManager],
    dependencies: Sequence[params.Depends],
) -> APIRouter:
    """
    The admin router of the streams a service reads. Mount it under the prefix the
    service wants (e.g. `/admin/streams`).

    - `GET /`: the overview of every stream (length, DLQ length, consumers, pending, lag).
    - `GET /{stream}`: the DLQ entries of a stream.
    - `POST /{stream}/{message_id}/replay`: runs the entry again.
    - `DELETE /{stream}/{message_id}`: removes the entry without running it.

    `dependencies` must hold the admin authorization of the service.
    """
    StreamName = Literal[tuple(streams)]  # type: ignore[valid-type]  # noqa: N806
    router = APIRouter(dependencies=list(dependencies))

    @router.get("/", response_model=list[StreamOverviewRead])
    async def overview():
        redis = get_redis()
        return [
            await stream_overview(redis, name, spec) for name, spec in streams.items()
        ]

    @router.get("/{stream_name}", response_model=list[DLQEntryRead])
    async def list_entries(stream_name: StreamName):  # type: ignore[valid-type]
        return await list_dlq_entries(get_redis(), stream_name)

    @router.post("/{stream_name}/{message_id}/replay", response_model=DLQReplayRead)
    async def replay(stream_name: StreamName, message_id: str):  # type: ignore[valid-type]
        outcome = await replay_dlq_entry(
            get_redis(), stream_name, streams[stream_name], message_id
        )
        return {"status": "replayed", "outcome": outcome, "message_id": message_id}

    @router.delete("/{stream_name}/{message_id}", response_model=DLQDiscardRead)
    async def discard(stream_name: StreamName, message_id: str):  # type: ignore[valid-type]
        await discard_dlq_entry(get_redis(), stream_name, message_id)
        return {"status": "discarded", "message_id": message_id}

    return router
