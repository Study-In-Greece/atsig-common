"""
The events that the services send each other over Redis Streams, defined once.

A producer builds an event with its model and sends `event.to_payload()`; a consumer
validates what it receives with the same model. Before, each side had its own copy
and the copies drifted apart (a field optional on one side, required on the other).

Not here yet: the call event (`calls_events`), which carries the nested documents,
disciplines and extra fields of a call and is still defined by each service.
"""

from .schemas import (
    DLQ_SUFFIX,
    Actions,
    ApplicantNameSync,
    EventPayload,
    ProgrammeUpdateEvent,
    Streams,
    UserDeleteEvent,
    UserSyncEvent,
    dlq_name,
    validation_problems,
)

__all__ = [
    "Actions",
    "ApplicantNameSync",
    "DLQ_SUFFIX",
    "EventPayload",
    "ProgrammeUpdateEvent",
    "Streams",
    "UserDeleteEvent",
    "UserSyncEvent",
    "dlq_name",
    "validation_problems",
]
