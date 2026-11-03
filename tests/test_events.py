import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from atsig_common.events import (
    Actions,
    ApplicantNameSync,
    ProgrammeUpdateEvent,
    Streams,
    UserDeleteEvent,
    UserSyncEvent,
    validation_problems,
)

UUID_1 = "3f1c9a52-8d2e-4c1b-9a77-0d6f3b1e2a44"


def test_the_stream_names_are_the_ones_the_services_use_today():
    assert Streams.CALLS == "calls_events"
    assert Streams.PROGRAMMES == "programme_updates"
    assert Streams.APPLICANT_NAMES == "update_applicant_applications"
    assert Streams.USERS == "user_events"
    assert Streams.SIS_EXPORTS == "sis_export_events"
    assert (Actions.SYNC, Actions.DELETE) == ("sync", "delete")


def test_name_sync_trims_the_names_and_reads_the_uuid():
    event = ApplicantNameSync.model_validate(
        {
            "applicant_id": UUID_1,
            "applicant_first_name": "  Ada ",
            "applicant_last_name": "Lovelace",
        }
    )

    assert event.applicant_id == UUID(UUID_1)
    assert event.applicant_first_name == "Ada"


@pytest.mark.parametrize(
    "bad",
    [
        {"applicant_id": "not-a-uuid"},
        {"applicant_first_name": ""},
        {"applicant_first_name": "   "},
        {"applicant_last_name": ""},
    ],
)
def test_name_sync_refuses_a_bad_uuid_or_an_empty_name(bad):
    payload = {
        "applicant_id": UUID_1,
        "applicant_first_name": "Ada",
        "applicant_last_name": "Lovelace",
        **bad,
    }

    with pytest.raises(ValidationError):
        ApplicantNameSync.model_validate(payload)


def test_to_payload_is_json_compatible():
    event = ApplicantNameSync(
        applicant_id=UUID(UUID_1), applicant_first_name="Ada", applicant_last_name="L"
    )

    payload = event.to_payload()

    assert payload["applicant_id"] == UUID_1  # a string, not a UUID object
    json.dumps(payload)  # does not raise


def test_unexpected_keys_are_named_not_validated():
    payload = {
        "applicant_id": UUID_1,
        "applicant_first_name": "Ada",
        "applicant_last_name": "L",
        "is_admin": True,
        "applicant_email": "ada@example.com",
    }

    assert ApplicantNameSync.unexpected_keys(payload) == ["applicant_email", "is_admin"]
    event = ApplicantNameSync.model_validate(payload)  # and they are ignored
    assert not hasattr(event, "is_admin")


def test_validation_problems_name_fields_and_types_never_values():
    with pytest.raises(ValidationError) as error:
        ApplicantNameSync.model_validate(
            {
                "applicant_id": "ada@example.com",
                "applicant_first_name": "",
                "applicant_last_name": "Lovelace",
            }
        )

    text = validation_problems(error.value)

    assert (
        text == "applicant_id (uuid_parsing), applicant_first_name (string_too_short)"
    )
    assert "ada@example.com" not in text
    assert "Lovelace" not in text


def test_a_user_event_accepts_uuid_or_the_older_id_key():
    new = UserSyncEvent.model_validate({"uuid": "u1", "email": "a@x.gr"})
    old = UserSyncEvent.model_validate({"id": "u1", "first_name": "Ada"})

    assert (new.uuid, old.uuid) == ("u1", "u1")
    assert old.email is None  # an update may carry only what changed
    assert UserSyncEvent.unexpected_keys({"id": "u1", "uuid": "u1"}) == []


def test_a_user_event_without_an_id_is_refused():
    with pytest.raises(ValidationError):
        UserSyncEvent.model_validate({"email": "a@x.gr"})
    with pytest.raises(ValidationError):
        UserDeleteEvent.model_validate({})


def test_user_events_round_trip():
    sync = UserSyncEvent(uuid="u1", email="a@x.gr", first_name="Ada", last_name="L")
    delete = UserDeleteEvent(uuid="u1")

    assert UserSyncEvent.model_validate(sync.to_payload()) == sync
    assert delete.to_payload() == {"uuid": "u1"}


PROGRAMME = {
    "id": 3,
    "name_gr": "Πρόγραμμα",
    "name_en": "Programme",
    "is_archived": False,
    "type": "Master",
    "department_id": 12,
    "secretaries": ["s1", "s2"],
    "version": 4,
}


def test_the_programme_event_round_trips():
    event = ProgrammeUpdateEvent.model_validate(PROGRAMME)

    assert event.to_payload() == PROGRAMME


def test_the_programme_event_defaults_and_requirements():
    event = ProgrammeUpdateEvent.model_validate(
        {k: v for k, v in PROGRAMME.items() if k != "type"}
    )

    assert event.type is None
    # `secretaries` is required: an event without it must not read as "no secretaries"
    # and clear the secretaries of the programme
    for required in (
        "id",
        "name_gr",
        "name_en",
        "is_archived",
        "department_id",
        "version",
        "secretaries",
    ):
        with pytest.raises(ValidationError):
            ProgrammeUpdateEvent.model_validate(
                {k: v for k, v in PROGRAMME.items() if k != required}
            )
