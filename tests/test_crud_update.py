from atsig_common.services.base import CRUDBaseService


class Row:
    id = 1
    name = "old"
    note = "old"


class FakeSession:
    async def flush(self):
        pass

    async def refresh(self, _obj):
        pass


async def test_update_with_a_dict_does_not_change_the_dict_of_the_caller():
    service = CRUDBaseService(Row, FakeSession())
    changes = {"name": "new", "secret_field": "x"}
    row = Row()

    await service.update(db_obj=row, obj_in=changes, exclude={"secret_field"})

    assert row.name == "new"
    assert not hasattr(row, "secret_field")
    assert changes == {"name": "new", "secret_field": "x"}
