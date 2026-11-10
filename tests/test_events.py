import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from atsig_common.events import (
    Actions,
    CallEvent,
    DepartmentEvent,
    LeadEvent,
    ProgrammeUpdateEvent,
    SchoolEvent,
    Streams,
    UniDeleteEvent,
    UniversityEvent,
    UserDeleteEvent,
    UserSyncEvent,
    validation_problems,
)

UUID_1 = "3f1c9a52-8d2e-4c1b-9a77-0d6f3b1e2a44"


def test_the_stream_names_are_the_ones_the_services_use_today():
    assert Streams.CALLS == "calls_events"
    assert Streams.PROGRAMMES == "programme_updates"
    assert Streams.USERS == "user_events"
    assert Streams.SIS_EXPORTS == "sis_export_events"
    assert (Actions.SYNC, Actions.DELETE) == ("sync", "delete")


def test_to_payload_is_json_compatible():
    event = UserSyncEvent(uuid=UUID_1, email="a@x.gr", first_name="Ada")

    payload = event.to_payload()

    assert payload == {
        "uuid": UUID_1,
        "email": "a@x.gr",
        "first_name": "Ada",
        "last_name": None,
    }
    json.dumps(payload)  # does not raise


def test_unexpected_keys_are_named_not_validated():
    payload = {
        "uuid": UUID_1,
        "email": "a@x.gr",
        "is_admin": True,
        "password": "secret",
    }

    assert UserSyncEvent.unexpected_keys(payload) == ["is_admin", "password"]
    event = UserSyncEvent.model_validate(payload)  # and they are ignored
    assert not hasattr(event, "is_admin")


def test_validation_problems_name_fields_and_types_never_values():
    with pytest.raises(ValidationError) as error:
        UniDeleteEvent.model_validate({"id": "ada@example.com", "version": "Lovelace"})

    text = validation_problems(error.value)

    assert text == "id (int_parsing), version (int_parsing)"
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
    payload = event.to_payload()

    # The fields the consumers rely on keep their values. The payload is a full snapshot,
    # so the rest of the programme is there too (None when the producer did not set it).
    assert {k: payload[k] for k in PROGRAMME} == PROGRAMME
    assert payload["admission_type"] is None and payload["tuition_fees"] is None
    assert ProgrammeUpdateEvent.model_validate(payload) == event


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


# --- call, programme (full snapshot) and lead events -----------------------------------

# What the programmes-api sent before this model existed: its own CallEvent was built from
# the API schema of a call, so the payload also carried created_at, is_open, call_file_url.
OLD_CALL_WIRE = {
    "title_gr": "Κλήση",
    "title_en": "Call",
    "description_gr": "Περιγραφή",
    "description_en": "Description",
    "academic_year": "2026-2027",
    "number_of_admissions": 20,
    "start_date": "2026-01-01",
    "end_date": "2026-03-01",
    "publish_date": "2025-12-01",
    "is_archived": False,
    "call_url": None,
    "evaluators": ["e@example.com"],
    "supported_attendance_modes": ["full_time"],
    "target_languages": ["Greek"],
    "restriction_mode": "none",
    "restricted_countries": [],
    "id": 7,
    "programme_id": 3,
    "call_type": "Master",
    "call_file": None,
    "is_open": True,
    "created_at": "2025-11-01T10:00:00Z",
    "updated_at": "2025-11-02T10:00:00Z",
    "call_file_url": None,
    "requested_documents": [
        {
            "document_type_code": "cv",
            "description_en": None,
            "description_gr": None,
            "is_required": True,
            "max_files": 1,
            "order_index": 0,
        }
    ],
    "version": 4,
    "disciplines": [
        {"discipline_id": 1, "title_en": "A", "title_gr": "Α", "order_index": 0}
    ],
    "extra_fields": [{"extra_field_code": "linkedin", "required": False}],
}


def test_the_call_event_accepts_what_the_producer_sent_before():
    event = CallEvent.model_validate(OLD_CALL_WIRE)
    assert event.id == 7 and event.programme_id == 3 and event.version == 4
    assert event.requested_documents[0].document_type_code == "cv"
    assert event.disciplines[0].title_gr == "Α"
    assert event.extra_fields[0].extra_field_code == "linkedin"
    assert event.evaluators == ["e@example.com"]
    # The fields of the API schema that no consumer stores are not part of the event
    assert CallEvent.unexpected_keys(OLD_CALL_WIRE) == [
        "call_file_url",
        "created_at",
        "is_open",
        "updated_at",
    ]
    assert not hasattr(event, "is_open")


def test_the_call_event_round_trips_through_its_payload():
    event = CallEvent.model_validate(OLD_CALL_WIRE)
    payload = event.to_payload()
    json.dumps(payload)
    assert CallEvent.model_validate(payload) == event
    assert payload["start_date"] == "2026-01-01"
    assert payload["call_type"] == "Master"
    assert payload["is_archived"] is False


def test_the_call_event_evaluators_keep_the_difference_between_none_and_empty():
    without = {**OLD_CALL_WIRE}
    without.pop("evaluators")
    assert CallEvent.model_validate(without).evaluators is None
    assert (
        CallEvent.model_validate({**OLD_CALL_WIRE, "evaluators": []}).evaluators == []
    )


def test_the_call_event_needs_its_required_fields():
    for missing in ("id", "programme_id", "version", "call_type", "start_date"):
        payload = {k: v for k, v in OLD_CALL_WIRE.items() if k != missing}
        with pytest.raises(ValidationError):
            CallEvent.model_validate(payload)


OLD_PROGRAMME_WIRE = {
    "id": 5,
    "name_gr": "Π",
    "name_en": "P",
    "is_archived": False,
    "type": "Master",
    "department_id": 12,
    "secretaries": [UUID_1],
    "version": 3,
}


def test_the_programme_event_still_accepts_the_old_payload():
    event = ProgrammeUpdateEvent.model_validate(OLD_PROGRAMME_WIRE)
    assert event.admission_type is None
    assert event.tuition_fees is None
    assert event.master_type is None
    assert ProgrammeUpdateEvent.unexpected_keys(OLD_PROGRAMME_WIRE) == []


def test_the_programme_event_carries_the_whole_programme():
    wire = {
        **OLD_PROGRAMME_WIRE,
        "admission_type": "internal",
        "description_gr": "Περιγραφή",
        "description_en": "Description",
        "collab_en_institutions": ["MIT"],
        "collaborations": [{"name": "MIT", "url": "https://mit.edu"}],
        "ects": 90,
        "city_en": "Athens",
        "city_gr": "Αθήνα",
        "phone": "2101234567",
        "email": "p@example.com",
        "website": "https://p.example.com",
        "languages": ["Greek", "English"],
        "topics": ["Engineering"],
        "study_modes": ["On campus"],
        "has_tuition_fees": True,
        "tuition_fees_from": "1000.50",
        "tuition_fees_to": "2000",
        "tuition_fees": [
            {
                "study_mode": "Full-Time",
                "student_origin": "EU",
                "period": "Per year",
                "amount": "1500.25",
            }
        ],
        "masters_id": 9,
        "is_featured": True,
        "created_at": "2025-11-01T10:00:00Z",
        "semesters": 3,
        "part_time": False,
        "part_time_semesters": None,
        "scholarship_offered": True,
        "master_type": "msc",
    }
    event = ProgrammeUpdateEvent.model_validate(wire)
    assert event.admission_type == "internal"
    assert event.tuition_fees[0].amount == Decimal("1500.25")
    assert event.tuition_fees_from == Decimal("1000.50")
    assert ProgrammeUpdateEvent.unexpected_keys(wire) == []
    payload = event.to_payload()
    json.dumps(payload)
    assert payload["tuition_fees"][0]["amount"] == "1500.25"
    assert ProgrammeUpdateEvent.model_validate(payload) == event


def test_the_programme_event_still_needs_the_fields_the_consumers_rely_on():
    for missing in ("id", "is_archived", "secretaries", "version", "department_id"):
        payload = {k: v for k, v in OLD_PROGRAMME_WIRE.items() if k != missing}
        with pytest.raises(ValidationError):
            ProgrammeUpdateEvent.model_validate(payload)


def test_the_lead_event_and_its_stream():
    assert Streams.LEADS == "programme_leads"
    wire = {
        "id": 1,
        "programme_id": 5,
        "first_name": "A",
        "last_name": "B",
        "email": "a@b.gr",
        "phone": None,
        "message": None,
        "origin_country": "Cyprus",
        "created_at": "2026-11-06T10:00:00Z",
    }
    event = LeadEvent.model_validate(wire)
    assert event.programme_id == 5 and event.phone is None
    json.dumps(event.to_payload())
    with pytest.raises(ValidationError):
        LeadEvent.model_validate({k: v for k, v in wire.items() if k != "programme_id"})


def test_the_uni_streams_are_one_per_entity():
    assert Streams.UNI_UNIVERSITIES == "uni_university_updates"
    assert Streams.UNI_SCHOOLS == "uni_school_updates"
    assert Streams.UNI_DEPARTMENTS == "uni_department_updates"


def test_the_university_event_round_trips_through_its_payload():
    event = UniversityEvent(
        id=1,
        name_gr="Πανεπιστήμιο",
        name_en="University",
        version=3,
        uni_type="1",
        establish_date="1990-01-01",
        website="https://uni.example",
        image="universities/1.png",
        image_url="https://cdn.example/universities/1.png?v=1",
    )

    payload = event.to_payload()
    json.dumps(payload)

    assert UniversityEvent.model_validate(payload) == event
    assert payload["establish_date"] == "1990-01-01"
    assert UniversityEvent.unexpected_keys(payload) == []


def test_the_school_and_department_events_keep_the_relations_as_ids():
    school = SchoolEvent(
        id=2, university_id=1, name_gr="Σχολή", name_en="School", version=1
    )
    department = DepartmentEvent.model_validate(
        {"id": 3, "name_gr": "Τμήμα", "name_en": "Dept", "version": 1, "school_id": 2}
    )

    assert school.status is True and school.minedu_code is None
    assert department.school_id == 2
    assert department.university_id is None  # nullable in the uni-api


@pytest.mark.parametrize(
    ("model", "payload", "missing"),
    [
        (UniversityEvent, {"id": 1, "name_gr": "a", "name_en": "b"}, "version"),
        (
            SchoolEvent,
            {"id": 1, "name_gr": "a", "name_en": "b", "version": 1},
            "university_id",
        ),
        (DepartmentEvent, {"id": 1, "name_gr": "a", "version": 1}, "name_en"),
        (UniDeleteEvent, {"id": 1}, "version"),
    ],
)
def test_the_uni_events_need_the_fields_the_consumers_rely_on(model, payload, missing):
    with pytest.raises(ValidationError) as caught:
        model.model_validate(payload)

    assert validation_problems(caught.value) == f"{missing} (missing)"


def test_the_uni_delete_event_carries_only_the_id_and_the_version():
    event = UniDeleteEvent.model_validate({"id": 4, "version": 7, "name_en": "ignored"})

    assert event.to_payload() == {"id": 4, "version": 7}
