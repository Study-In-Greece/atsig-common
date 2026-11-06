from datetime import date, datetime
from decimal import Decimal
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

from atsig_common.enums import AttendanceMode, Languages, ProgrammeType, RestrictionMode


class Streams:
    """The names of the Redis streams. Producers and consumers must agree on them."""

    CALLS = "calls_events"
    PROGRAMMES = "programme_updates"
    APPLICANT_NAMES = "update_applicant_applications"
    USERS = "user_events"
    SIS_EXPORTS = "sis_export_events"
    # A lead (a visitor interested in a programme) was saved. Nobody consumes it yet.
    LEADS = "programme_leads"


class Actions:
    SYNC = "sync"
    DELETE = "delete"
    # What an admin screen shows for a DLQ entry that can not be read back
    UNREADABLE = "unreadable"


DLQ_SUFFIX = "_dlq"


def dlq_name(stream_name: str) -> str:
    """The name of the dead letter stream of a stream (`calls_events` -> `calls_events_dlq`)."""
    return f"{stream_name}{DLQ_SUFFIX}"


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


class TuitionFeeEvent(EventPayload):
    """One tuition fee of a programme (a row of `tuition_fee`)."""

    study_mode: str
    student_origin: str
    period: str
    amount: Decimal


class ProgrammeUpdateEvent(EventPayload):
    """
    A programme changed (programmes-api, stream `programme_updates`, action sync). A full
    snapshot of the programme: `version` grows with every change (also when only a child
    changes, like the secretaries or the tuition fees), and a consumer ignores a version
    that is not newer than the one it stores.

    `is_archived` is the programme's own flag. Whether the programme takes applications
    through the system is up to the consumer to decide, from `admission_type`
    (`internal` takes them) and `is_archived`.

    Only `id`, the names, `is_archived`, `department_id`, `secretaries` and `version`
    are required: the rest is optional so that an older producer, or an event that is
    already in the stream, still validates. The enums of the programmes-api (topics,
    study modes, master/bachelor/short term types, fee kinds) travel as plain strings.
    """

    id: int
    name_gr: str
    name_en: str
    is_archived: bool
    type: str | None = None
    department_id: int
    secretaries: list[str]
    version: int

    admission_type: str | None = None

    description_gr: str | None = None
    description_en: str | None = None
    collab_en_institutions: list[str] | None = None
    collaborations: list[dict[str, Any]] | None = None
    ects: int | None = None
    city_en: str | None = None
    city_gr: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    languages: list[str] | None = None
    topics: list[str] | None = None
    study_modes: list[str] | None = None
    has_tuition_fees: bool | None = None
    tuition_fees_from: Decimal | None = None
    tuition_fees_to: Decimal | None = None
    tuition_fees: list[TuitionFeeEvent] | None = None
    masters_id: int | None = None
    is_featured: bool | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # The fields of one kind of programme (None for the others)
    semesters: int | None = None
    part_time: bool | None = None
    part_time_semesters: int | None = None
    scholarship_offered: bool | None = None
    master_type: str | None = None
    bachelor_type: str | None = None
    days: int | None = None
    short_term_type: str | None = None


class CallRequestedDocumentEvent(EventPayload):
    """A document that a call asks for (by the code of its document type)."""

    document_type_code: str
    description_en: str | None = None
    description_gr: str | None = None
    is_required: bool = True
    max_files: int = 1
    order_index: int


class CallDisciplineEvent(EventPayload):
    """A discipline of a call, with its titles at the time of the event."""

    discipline_id: int
    title_en: str
    title_gr: str
    order_index: int = 0


class CallExtraFieldEvent(EventPayload):
    """An extra field that a call asks the applicant for (by its code)."""

    extra_field_code: str
    required: bool = False


class CallEvent(EventPayload):
    """
    A call changed (programmes-api, stream `calls_events`, action sync). A full snapshot,
    children included: `version` grows with every change of the call or of anything it
    carries, and a consumer ignores a version that is not newer than the one it has.

    `is_archived` is the call's own flag. A call is hidden also when its programme is
    archived, and that is up to the consumer (it has the programme event).

    `evaluators`: None leaves the evaluators of the consumer alone, an empty list
    removes all of them, a list sets them.
    """

    id: int
    programme_id: int
    title_gr: str
    title_en: str
    description_gr: str
    description_en: str
    academic_year: str
    number_of_admissions: int | None = None
    start_date: date
    end_date: date
    publish_date: date
    call_url: str | None = None
    call_type: ProgrammeType
    call_file: str | None = None
    is_archived: bool = False
    supported_attendance_modes: list[AttendanceMode] = [AttendanceMode.undetermined]
    target_languages: list[Languages] = []
    restriction_mode: RestrictionMode = RestrictionMode.none
    restricted_countries: list[str] = []
    version: int
    evaluators: list[str] | None = None
    requested_documents: list[CallRequestedDocumentEvent] = []
    disciplines: list[CallDisciplineEvent] = []
    extra_fields: list[CallExtraFieldEvent] = []


class LeadEvent(EventPayload):
    """
    A lead was saved: a visitor who is interested in a programme (programmes-api, stream
    `programme_leads`, action sync). It carries personal data, so the producer caps the
    length of the stream.
    """

    id: int
    programme_id: int
    first_name: str
    last_name: str
    email: str
    phone: str | None = None
    message: str | None = None
    origin_country: str
    created_at: datetime | None = None
