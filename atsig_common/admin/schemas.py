from typing import Literal

from pydantic import BaseModel

from atsig_common.redis.consumer import ConsumerOutcome


class DLQEntryRead(BaseModel):
    dlq_message_id: str
    original_message_id: str
    action: str
    payload: dict
    error: str
    consumer_group: str


class DLQReplayRead(BaseModel):
    status: Literal["replayed"]
    outcome: ConsumerOutcome
    message_id: str


class DLQDiscardRead(BaseModel):
    status: Literal["discarded"]
    message_id: str


class StreamOverviewRead(BaseModel):
    """One stream as this service reads it."""

    stream: str
    group: str
    length: int
    dlq_length: int
    consumers: int
    pending: int
    # Entries the group has not read yet (None when Redis cannot tell)
    lag: int | None = None
    replayable: bool


class ResyncJobRead(BaseModel):
    name: str
    description: str
    params: dict | None = None  # JSON schema of the optional parameters
    state: Literal["idle", "running", "ok", "error"] = "idle"
    count: int | None = None
    error: str | None = None  # the TYPE of the exception only
    started_at: str | None = None
    finished_at: str | None = None
