"""
The events that the services send each other over Redis Streams, defined once.

A producer builds an event with its model and sends `event.to_payload()`; a consumer
validates what it receives with the same model. Before, each side had its own copy
and the copies drifted apart (a field optional on one side, required on the other).

The call event (`calls_events`) carries the nested documents, disciplines and extra
fields of a call; the lead event (`programme_leads`) is sent by the programmes-api and
nobody consumes it yet.
"""

from .schemas import (
    DLQ_SUFFIX,
    Actions,
    ApplicantNameSync,
    CallDisciplineEvent,
    CallEvent,
    CallExtraFieldEvent,
    CallRequestedDocumentEvent,
    EventPayload,
    LeadEvent,
    ProgrammeUpdateEvent,
    Streams,
    TuitionFeeEvent,
    UserDeleteEvent,
    UserSyncEvent,
    dlq_name,
    validation_problems,
)

__all__ = [
    "Actions",
    "ApplicantNameSync",
    "CallDisciplineEvent",
    "CallEvent",
    "CallExtraFieldEvent",
    "CallRequestedDocumentEvent",
    "DLQ_SUFFIX",
    "EventPayload",
    "LeadEvent",
    "ProgrammeUpdateEvent",
    "Streams",
    "TuitionFeeEvent",
    "UserDeleteEvent",
    "UserSyncEvent",
    "dlq_name",
    "validation_problems",
]
