"""KeycloakUserService and NewIdentityTracker against a fake admin client (no network)."""

import pytest
from keycloak import KeycloakPostError

from atsig_common.exceptions import AtsigError, ConflictError
from atsig_common.keycloak_admin import (
    INVITE_ACTIONS,
    KeycloakUserCreate,
    KeycloakUserService,
    KeycloakUserUpdate,
    NewIdentityTracker,
)


class FakeAdmin:
    def __init__(self):
        self.calls: list[tuple] = []
        self.created_payload: dict | None = None
        self.exists = False
        self.fail_group_add = False
        self.fail_send = False
        self.delete_status: int | None = None
        self.users = [{"id": "existing-id"}]

    def create_user(self, payload, exist_ok=False):
        self.calls.append(("create_user",))
        self.created_payload = payload
        if self.exists:
            raise KeycloakPostError(response_code=409, error_message="exists")
        return "new-id"

    def get_group_by_path(self, path):
        return {"id": f"gid:{path}"}

    def group_user_add(self, user_id, group_id):
        self.calls.append(("group_user_add", user_id, group_id))
        if self.fail_group_add:
            raise RuntimeError("boom")

    def group_user_remove(self, user_id, group_id):
        self.calls.append(("group_user_remove", user_id, group_id))

    def get_users(self, query=None):
        return self.users

    def delete_user(self, user_id):
        self.calls.append(("delete_user", user_id))
        if self.delete_status:
            err = RuntimeError("x")
            err.response_code = self.delete_status
            raise err

    def send_update_account(self, user_id, payload, lifespan=None, **kw):
        self.calls.append(("send_update_account", user_id, payload, lifespan))
        if self.fail_send:
            raise RuntimeError("smtp")

    def update_user(self, user_id, payload):
        self.calls.append(("update_user", user_id, payload))


def user(group="/Secretary"):
    return KeycloakUserCreate(
        username="a@b.gr",
        email="a@b.gr",
        first_name="A",
        last_name="B",
        group_path=group,
    )


def test_create_user_has_no_password_and_requires_password_action():
    admin = FakeAdmin()
    svc = KeycloakUserService(admin)
    assert "password" not in KeycloakUserCreate.model_fields
    assert svc.create_user(user()) == ("new-id", True)
    assert admin.created_payload["requiredActions"] == INVITE_ACTIONS
    assert "credentials" not in admin.created_payload


def test_create_user_moves_out_of_default_group():
    admin = FakeAdmin()
    KeycloakUserService(admin).create_user(user("/Secretary"))
    assert ("group_user_add", "new-id", "gid:/Secretary") in admin.calls
    assert ("group_user_remove", "new-id", "gid:/Applicants") in admin.calls


def test_create_user_in_default_group_does_not_touch_groups():
    admin = FakeAdmin()
    KeycloakUserService(admin).create_user(user("/Applicants"))
    assert not [c for c in admin.calls if c[0].startswith("group_")]


def test_existing_user_without_flag_is_a_conflict_and_untouched():
    admin = FakeAdmin()
    admin.exists = True
    with pytest.raises(ConflictError):
        KeycloakUserService(admin).create_user(user())
    assert not [c for c in admin.calls if c[0] != "create_user"]


def test_existing_user_with_flag_moves_group_and_is_not_new():
    admin = FakeAdmin()
    admin.exists = True
    result = KeycloakUserService(admin).create_user(user(), allow_existing_user=True)
    assert result == ("existing-id", False)
    assert ("group_user_add", "existing-id", "gid:/Secretary") in admin.calls


def test_failure_after_create_rolls_the_new_user_back():
    admin = FakeAdmin()
    admin.fail_group_add = True
    with pytest.raises(AtsigError):
        KeycloakUserService(admin).create_user(user())
    assert ("delete_user", "new-id") in admin.calls


def test_invite_sends_the_actions_and_never_raises():
    admin = FakeAdmin()
    svc = KeycloakUserService(admin)
    assert svc.invite_user("u1") is True
    assert admin.calls[-1][:3] == ("send_update_account", "u1", INVITE_ACTIONS)
    admin.fail_send = True
    assert svc.invite_user("u1") is False


def test_delete_counts_404_as_gone_and_other_errors_as_failure():
    admin = FakeAdmin()
    svc = KeycloakUserService(admin)
    admin.delete_status = 404
    assert svc.delete_user("x") is True
    admin.delete_status = 500
    assert svc.delete_user("x") is False


def test_update_maps_names_to_camel_case():
    admin = FakeAdmin()
    KeycloakUserService(admin).update_user("u", KeycloakUserUpdate(first_name="N"))
    assert admin.calls[-1] == ("update_user", "u", {"firstName": "N"})


async def test_adelete_gives_up_after_the_attempts():
    admin = FakeAdmin()
    admin.delete_status = 500
    svc = KeycloakUserService(admin)
    assert await svc.adelete_user("x", attempts=2, delay=0) is False
    assert [c for c in admin.calls if c[0] == "delete_user"] == [
        ("delete_user", "x")
    ] * 2


class FakeSession:
    def __init__(self, fail=False):
        self.fail = fail

    async def commit(self):
        if self.fail:
            raise RuntimeError("commit")


async def test_tracker_discards_only_what_this_request_created():
    admin = FakeAdmin()
    tracker = NewIdentityTracker(KeycloakUserService(admin))
    tracker.track("mine")
    await tracker.discard("other")
    assert not [c for c in admin.calls if c[0] == "delete_user"]
    await tracker.discard("mine")
    assert ("delete_user", "mine") in admin.calls


async def test_tracker_commit_failure_removes_new_accounts_and_reraises():
    admin = FakeAdmin()
    tracker = NewIdentityTracker(KeycloakUserService(admin))
    tracker.track("a")
    with pytest.raises(RuntimeError):
        await tracker.commit_or_discard(FakeSession(fail=True))
    assert ("delete_user", "a") in admin.calls


async def test_tracker_commit_success_keeps_the_accounts():
    admin = FakeAdmin()
    tracker = NewIdentityTracker(KeycloakUserService(admin))
    tracker.track("a")
    await tracker.commit_or_discard(FakeSession())
    assert tracker.new_ids == []
    assert not [c for c in admin.calls if c[0] == "delete_user"]
