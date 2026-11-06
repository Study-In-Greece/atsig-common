import json

import pytest
from pydantic import ValidationError

from atsig_common.schemas import FileUrlRead, IdRead


def test_id_read_gives_the_same_json_as_the_dict_the_routes_returned():
    assert IdRead.model_validate({"id": 12}).model_dump(mode="json") == {"id": 12}
    assert json.dumps(IdRead(id=3).model_dump()) == json.dumps({"id": 3})


def test_file_url_read_gives_the_same_json_as_the_dict_the_routes_returned():
    url = "https://bucket.example/applicants/u1/cv/x.pdf?sig=abc&exp=1"
    assert FileUrlRead.model_validate({"url": url}).model_dump(mode="json") == {
        "url": url
    }


def test_the_schemas_have_exactly_the_fields_of_the_old_dicts():
    assert set(IdRead.model_fields) == {"id"}
    assert set(FileUrlRead.model_fields) == {"url"}


def test_a_missing_field_is_an_error_and_an_extra_one_is_dropped():
    with pytest.raises(ValidationError):
        IdRead.model_validate({})
    with pytest.raises(ValidationError):
        FileUrlRead.model_validate({"detail": "x"})
    assert IdRead.model_validate({"id": 1, "other": 2}).model_dump() == {"id": 1}
