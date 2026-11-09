"""UserMixin and UserService against fakes (no database, no Keycloak, no Redis)."""

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import inspect
from sqlalchemy.orm import DeclarativeBase

from atsig_common.db.mixins import TimestampMixin
from atsig_common.events import Actions, Streams
from atsig_common.exceptions import ConflictError, NotFoundError
from atsig_common.keycloak_admin import KeycloakUserService
from atsig_common.users import (
    UserCreate,
    UserLocalCreate,
    UserMixin,
    UserService,
    UserUpdate,
)


class Base(DeclarativeBase):
    pass


class User(Base, TimestampMixin, UserMixin):
    __tablename__ = "user"


class FakeAdmin:
    def __init__(self):
        self.calls: list[tuple] = []
        self.exists = False

    def create_user(self, payload, exist_ok=False):
        self.calls.append(("create_user", payload["email"]))
        if self.exists:
            from keycloak import KeycloakPostError

            raise KeycloakPostError(response_code=409, error_message="exists")
        return "kc-1"

    def get_group_by_path(self, path):
        return {"id": f"gid:{path}"}

    def group_user_add(self, user_id, group_id):
        pass

    def group_user_remove(self, user_id, group_id):
        pass

    def get_users(self, query=None):
        return [{"id": "kc-existing"}]

    def delete_user(self, user_id):
        self.calls.append(("delete_user", user_id))

    def update_user(self, user_id, payload):
        self.calls.append(("update_user", user_id, payload))

    def send_update_account(self, user_id, payload, lifespan=None, **kw):
        self.calls.append(("invite", user_id))


class FakeProducer:
    def __init__(self):
        self.events: list[dict] = []

    async def emit_safe(self, **kwargs):
        self.events.append(kwargs)


class FakeSession:
    def __init__(self):
        self.rows: dict[str, User] = {}
        self.fail_flush = False
        self.fail_commit = False
        self.commits = 0

    def add(self, obj):
        self.rows[obj.uuid] = obj

    async def flush(self):
        if self.fail_flush:
            self.rows.clear()
            raise RuntimeError("flush")

    async def get(self, model, key):
        return self.rows.get(key)

    async def delete(self, obj):
        self.rows.pop(obj.uuid, None)

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("commit")
        self.commits += 1


class Service(UserService):
    """The lookups that run SQL are answered from the fake session."""

    async def get(self, resource_id):
        return self.session.rows.get(resource_id)

    async def get_user_by_email(self, email):
        return next((u for u in self.session.rows.values() if u.email == email), None)


def make():
    admin, producer, session = FakeAdmin(), FakeProducer(), FakeSession()
    svc = Service(User, session, KeycloakUserService(admin), producer)
    return svc, admin, producer, session


async def run_tasks(bg: BackgroundTasks):
    for task in bg.tasks:
        await task()


def new_user():
    return UserCreate(
        email="a@b.gr", first_name="A", last_name="B", group_path="/Secretary"
    )


def test_mixin_gives_the_table_the_profiles_api_schema():
    table = inspect(User).local_table
    cols = {c.name: c for c in table.columns}
    assert set(cols) == {
        "uuid",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "group_path",
        "created_at",
        "updated_at",
    }
    assert cols["uuid"].primary_key
    assert not cols["email"].nullable and not cols["first_name"].nullable
    assert cols["group_path"].nullable
    assert cols["is_active"].server_default.arg == "true"
    email_index = next(i for i in table.indexes if "email" in i.columns)
    assert email_index.name == "ix_user_email" and email_index.unique


def test_user_create_has_no_password():
    assert "password" not in UserCreate.model_fields


async def test_create_user_uses_the_keycloak_id_and_emits_a_sync_event():
    svc, admin, producer, session = make()
    bg = BackgroundTasks()
    user = await svc.create_user(bg, new_user())
    assert user.uuid == "kc-1" and session.rows["kc-1"].email == "a@b.gr"
    await run_tasks(bg)
    assert producer.events[0]["stream_name"] == Streams.USERS
    assert producer.events[0]["action"] == Actions.SYNC
    assert producer.events[0]["payload"]["uuid"] == "kc-1"


async def test_failed_flush_removes_the_keycloak_user_this_request_created():
    svc, admin, _, session = make()
    session.fail_flush = True
    with pytest.raises(RuntimeError):
        await svc.create_user(BackgroundTasks(), new_user())
    assert ("delete_user", "kc-1") in admin.calls


async def test_failed_flush_never_removes_an_account_that_existed():
    svc, admin, _, session = make()
    admin.exists = True
    session.fail_flush = True
    with pytest.raises(RuntimeError):
        await svc.create_user(BackgroundTasks(), new_user(), allow_existing_user=True)
    assert not [c for c in admin.calls if c[0] == "delete_user"]


async def test_existing_email_without_the_flag_is_a_conflict():
    svc, admin, _, _ = make()
    admin.exists = True
    with pytest.raises(ConflictError):
        await svc.create_user(BackgroundTasks(), new_user())


async def test_commit_invites_only_after_the_commit_succeeded():
    svc, admin, _, session = make()
    await svc.create_user(BackgroundTasks(), new_user())
    await svc.commit()
    assert session.commits == 1
    assert admin.calls[-1] == ("invite", "kc-1")


async def test_failed_commit_deletes_the_account_and_sends_no_invite():
    svc, admin, _, session = make()
    await svc.create_user(BackgroundTasks(), new_user())
    session.fail_commit = True
    with pytest.raises(RuntimeError):
        await svc.commit()
    assert ("delete_user", "kc-1") in admin.calls
    assert not [c for c in admin.calls if c[0] == "invite"]


async def test_existing_account_is_not_invited():
    svc, admin, _, _ = make()
    admin.exists = True
    await svc.create_user(BackgroundTasks(), new_user(), allow_existing_user=True)
    await svc.commit()
    assert not [c for c in admin.calls if c[0] == "invite"]


async def test_local_create_refuses_a_duplicate_email():
    svc, *_ = make()
    data = UserLocalCreate(
        email="a@b.gr", first_name="A", last_name="B", group_path="/Applicants"
    )
    await svc.create_local_user_only(BackgroundTasks(), data, user_uuid="u1")
    with pytest.raises(ConflictError):
        await svc.create_local_user_only(BackgroundTasks(), data, user_uuid="u2")


async def test_delete_removes_the_row_then_keycloak_then_emits_after_the_request():
    svc, admin, producer, session = make()
    await svc.create_user(BackgroundTasks(), new_user())
    bg = BackgroundTasks()
    await svc.delete_user(bg, "kc-1")
    assert "kc-1" not in session.rows
    assert not [c for c in admin.calls if c[0] == "delete_user"]  # not yet
    await run_tasks(bg)
    assert ("delete_user", "kc-1") in admin.calls
    assert producer.events[-1]["action"] == Actions.DELETE


async def test_update_changes_keycloak_and_the_row_and_emits():
    svc, admin, producer, session = make()
    await svc.create_user(BackgroundTasks(), new_user())
    bg = BackgroundTasks()
    await svc.update_user(bg, "kc-1", UserUpdate(first_name="New"))
    assert session.rows["kc-1"].first_name == "New"
    assert admin.calls[-1][0] == "update_user"
    await run_tasks(bg)
    assert producer.events[-1]["payload"]["first_name"] == "New"


async def test_update_of_a_missing_user_is_a_404():
    svc, *_ = make()
    with pytest.raises(NotFoundError):
        await svc.update_user(BackgroundTasks(), "nope", UserUpdate(first_name="x"))


async def test_sync_creates_then_updates():
    svc, *_ = make()
    data = UserLocalCreate(
        email="a@b.gr", first_name="A", last_name="B", group_path="/Applicants"
    )
    bg = BackgroundTasks()
    await svc.sync_local_user(bg, data, "u1")
    data2 = data.model_copy(update={"first_name": "Z"})
    user = await svc.sync_local_user(bg, data2, "u1")
    assert user.first_name == "Z"
    assert len(bg.tasks) == 2
