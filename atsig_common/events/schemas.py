from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
)


class Streams:
    """The names of the Redis streams. Producers and consumers must agree on them."""

    CALLS = "calls_events"
    PROGRAMMES = "programme_updates"
    APPLICANT_NAMES = "update_applicant_applications"
    USERS = "user_events"
    SIS_EXPORTS = "sis_export_events"


class Actions:
    SYNC = "sync"
    DELETE = "delete"


def validation_problems(error: ValidationError) -> str:
    """
    The problems of a failed validation as `loc (type), loc (type)`.

    This is what goes into the message of a NonRetryableError, and so into the logs and
    the DLQ: it names the fields and the kind of problem, and never the values (the
    input of a bad event can be a name or an email).
    """
    return ", ".join(
        f"{'.'.join(str(part) for part in problem['loc'])} ({problem['type']})"
        for problem in error.errors(
            include_url=False, include_context=False, include_input=False
        )
    )


class EventPayload(BaseModel):
    """Base of the events. Keys that the model does not know are ignored."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    @classmethod
    def unexpected_keys(cls, payload: dict[str, Any]) -> list[str]:
        """The keys of a payload that the model does not know (to log them by name)."""
        known = set(cls.model_fields)
        for field in cls.model_fields.values():
            alias = field.validation_alias
            if isinstance(alias, AliasChoices):
                known.update(
                    choice for choice in alias.choices if isinstance(choice, str)
                )
            elif isinstance(alias, str):
                known.add(alias)
        return sorted(set(payload) - known)

    def to_payload(self) -> dict[str, Any]:
        """The dict to send as the payload of the stream entry (JSON-compatible)."""
        return self.model_dump(mode="json")


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApplicantNameSync(EventPayload):
    """
    The names of an applicant changed (profiles-api, stream `update_applicant_applications`).
    The applications-api updates the names on every application of the applicant, and
    nothing else: this event can not change any other field.
    """

    applicant_id: UUID
    applicant_first_name: Name
    applicant_last_name: Name


class UserSyncEvent(EventPayload):
    """A user was created or changed (profiles-api, stream `user_events`, action sync)."""

    uuid: str = Field(validation_alias=AliasChoices("uuid", "id"))
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class UserDeleteEvent(EventPayload):
    """A user was deleted (profiles-api, stream `user_events`, action delete)."""

    uuid: str = Field(validation_alias=AliasChoices("uuid", "id"))


class ProgrammeUpdateEvent(EventPayload):
    """
    A programme changed (programmes-api, stream `programme_updates`, action sync). A full
    snapshot: `version` grows with every change, and a consumer ignores a version that
    is not newer than the one it stores.
    """

    id: int
    name_gr: str
    name_en: str
    is_archived: bool
    type: str | None = None
    department_id: int
    secretaries: list[str]
    version: int
