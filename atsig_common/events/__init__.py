"""
The events that the services send each other over Redis Streams, defined once.

A producer builds an event with its model and sends `event.to_payload()`; a consumer
validates what it receives with the same model. Before, each side had its own copy
and the copies drifted apart (a field optional on one side, required on the other).

Not here yet: the call event (`calls_events`), which carries the nested documents,
disciplines and extra fields of a call and is still defined by each service.
"""

from .schemas import (
    Actions,
    ApplicantNameSync,
    EventPayload,
    ProgrammeUpdateEvent,
    Streams,
    UserDeleteEvent,
    UserSyncEvent,
    validation_problems,
)

__all__ = [
    "Actions",
    "ApplicantNameSync",
    "EventPayload",
    "ProgrammeUpdateEvent",
    "Streams",
    "UserDeleteEvent",
    "UserSyncEvent",
    "validation_problems",
]
