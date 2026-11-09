"""
The Keycloak admin side of the users, shared by the services that create accounts.

The `KeycloakAdmin` client is synchronous (`requests`) and shared by the whole process.
Its token refresh is not safe from several threads at once, so the calls take turns
(`_admin_lock`) and run off the event loop (`asyncio.to_thread`).
"""

import asyncio
import logging
import threading
from typing import Any

from keycloak import KeycloakAdmin, KeycloakGetError, KeycloakPostError

from ..auth.groups import GroupEnum
from ..exceptions import AtsigError, BadRequestError, ConflictError, NotFoundError
from .schemas import KeycloakUserCreate, KeycloakUserUpdate

logger = logging.getLogger("keycloak-service")

# What a new account has to do on first login. The password is set from the link of the
# invitation email, never by us.
INVITE_ACTIONS = ["UPDATE_PASSWORD", "UPDATE_PROFILE"]
# Lifetime of the invitation link, in seconds (3 days)
INVITE_LIFESPAN = 3 * 24 * 3600

_admin_lock = threading.Lock()


async def _in_thread(func, *args, **kwargs):
    """Runs a blocking Keycloak call in a thread, so the event loop keeps serving."""

    def run():
        with _admin_lock:
            return func(*args, **kwargs)

    return await asyncio.to_thread(run)


def create_keycloak_admin(settings: Any) -> KeycloakAdmin:
    """
    Builds the admin client from the settings (`KEYCLOAK_ADMIN_CLIENT_ID` and
    `KEYCLOAK_ADMIN_CLIENT_SECRET` must be set).
    """
    if (
        not settings.KEYCLOAK_ADMIN_CLIENT_ID
        or not settings.KEYCLOAK_ADMIN_CLIENT_SECRET
    ):
        raise ValueError("KEYCLOAK_ADMIN_CLIENT_ID/SECRET are not set")
    return KeycloakAdmin(
        server_url=settings.AUTHORIZATION_URL,
        client_id=settings.KEYCLOAK_ADMIN_CLIENT_ID,
        realm_name=settings.KEYCLOAK_REALM,
        client_secret_key=settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
        user_realm_name=settings.KEYCLOAK_REALM,
        verify=settings.KEYCLOAK_VERIFY_SSL,
    )


class KeycloakUserService:
    """
    The `create_user`, `update_user`, `delete_user`, `invite_user` and `get_user_by_id`
    methods block: code that runs on the event loop uses the `a...` versions
    (`acreate_user`, `aupdate_user`, `adelete_user`, `ainvite_user`) and
    `get_user_by_id_with_retry`.

    The messages of the errors that reach the client and the log lines hold no detail of
    the Keycloak answer (it can carry emails): the exception type and the HTTP status.
    """

    def __init__(self, admin: KeycloakAdmin):
        self.admin = admin
        self.default_group = GroupEnum.APPLICANT.value

    def _get_group_id_by_path(self, group_path: str) -> str:
        """Returns the internal Keycloak id of a group from its path (e.g. /Applicants)."""
        try:
            group = self.admin.get_group_by_path(path=group_path)
            if not group:
                raise NotFoundError(f"Keycloak group path '{group_path}' not found")
            return group["id"]
        except KeycloakGetError as e:
            logger.error(
                f"Keycloak group lookup failed (HTTP {e.response_code}) for path {group_path}"
            )
            raise NotFoundError(
                f"Keycloak group path '{group_path}' does not exist"
            ) from e
        except Exception as e:
            if isinstance(e, NotFoundError):
                raise e
            logger.error(f"Keycloak group lookup failed: {type(e).__name__}")
            raise AtsigError("Keycloak group lookup failed.") from None

    def get_all_users(self):
        """Fetches all users from the Keycloak realm."""
        return self.admin.get_users()

    def get_user_groups(self, user_id: str) -> list[str]:
        """Returns a list of group paths (e.g., ['/Applicants']) for a user."""
        groups = self.admin.get_user_groups(user_id=user_id)
        return [g["path"] for g in groups]

    def _move_to_group(self, user_id: str, group_path: str) -> None:
        """Puts the user in `group_path` and out of the default group."""
        if group_path == self.default_group:
            return
        new_group_id = self._get_group_id_by_path(group_path)
        default_group_id = self._get_group_id_by_path(self.default_group)
        self.admin.group_user_add(user_id=user_id, group_id=new_group_id)
        self.admin.group_user_remove(user_id=user_id, group_id=default_group_id)

    def create_user(
        self, user_data: KeycloakUserCreate, allow_existing_user: bool = False
    ) -> tuple[str, bool]:
        """
        Creates the user in Keycloak (without a password) and returns the Keycloak UUID
        and True.

        When the user already exists (409) and `allow_existing_user` is False, nothing is
        changed in Keycloak and a ConflictError is raised: the group of an existing
        account must not be changed by whoever knows its email. When it is True, the
        existing user is added to the new group and (UUID, False) is returned.
        """
        user_id = None  # set before the try: the except below reads it

        try:
            user_payload = {
                "username": user_data.username,
                "email": user_data.email,
                "firstName": user_data.first_name,
                "lastName": user_data.last_name,
                "enabled": user_data.enabled,
                "emailVerified": True,
                "attributes": user_data.attributes,
                "requiredActions": INVITE_ACTIONS,
            }
            user_id = self.admin.create_user(user_payload, exist_ok=False)
            self._move_to_group(user_id, user_data.group_path)
            return user_id, True

        except KeycloakPostError as e:
            if e.response_code == 409:
                if not allow_existing_user:
                    raise ConflictError("A user with this email already exists.") from e

                logger.info("The user already exists in Keycloak. Updating groups.")
                users = self.admin.get_users({"email": user_data.email})
                if not users:
                    users = self.admin.get_users({"username": user_data.username})
                if not users:
                    raise AtsigError(
                        "User reported as existing, but cannot be fetched."
                    ) from None

                existing_user_id = users[0]["id"]
                self._move_to_group(existing_user_id, user_data.group_path)
                return existing_user_id, False

            logger.error(f"Keycloak refused to create a user (HTTP {e.response_code})")
            raise AtsigError("Failed to create the user in Keycloak.") from None

        except Exception as e:
            # With a user_id the failure came after the create (the group): roll back
            if user_id:
                logger.warning(
                    f"[KeycloakService] Internal error after creation. Rolling back user {user_id}"
                )
                try:
                    self.delete_user(user_id)
                except Exception as rollback_err:
                    logger.error(
                        f"CRITICAL: Internal rollback failed for {user_id}: {type(rollback_err).__name__}"
                    )

            if isinstance(
                e, (ConflictError, BadRequestError, NotFoundError, AtsigError)
            ):
                raise e

            logger.error(f"Unexpected error in Keycloak create: {type(e).__name__}")
            raise AtsigError("Failed to create the user in Keycloak.") from None

    def invite_user(
        self,
        user_id: str,
        actions: list[str] | None = None,
        lifespan: int = INVITE_LIFESPAN,
    ) -> bool:
        """
        Asks Keycloak to email the user a link that performs `actions` (by default the
        password and profile set-up). Returns False, never raises: the account exists
        and can be invited again, so a failed email must not fail the request.
        """
        try:
            self.admin.send_update_account(
                user_id=user_id,
                payload=actions or INVITE_ACTIONS,
                lifespan=lifespan,
            )
            return True
        except Exception as e:
            logger.error(
                f"Keycloak invitation email failed for {user_id}: {type(e).__name__} "
                f"(HTTP {getattr(e, 'response_code', None)})"
            )
            return False

    def delete_user(self, user_id: str) -> bool:
        """
        Deletes the user from Keycloak and returns True when the user is gone (one that
        was already gone counts). A failure is logged and returns False: the caller
        decides what to do, because an orphan user in Keycloak can still log in.
        """
        try:
            self.admin.delete_user(user_id=user_id)
            return True
        except Exception as e:
            if getattr(e, "response_code", None) == 404:
                return True
            logger.error(
                f"CRITICAL: Failed to delete Keycloak user {user_id}: {type(e).__name__} "
                f"(HTTP {getattr(e, 'response_code', None)})"
            )
            return False

    def update_user(self, user_id: str, update_data: KeycloakUserUpdate):
        payload = update_data.model_dump(exclude_none=True)

        # Keycloak expects camelCase for the basic fields
        if "first_name" in payload:
            payload["firstName"] = payload.pop("first_name")
        if "last_name" in payload:
            payload["lastName"] = payload.pop("last_name")

        try:
            self.admin.update_user(user_id=user_id, payload=payload)
        except Exception as e:
            logger.error(f"Keycloak API error during update: {type(e).__name__}")
            raise e

    async def acreate_user(
        self, user_data: KeycloakUserCreate, allow_existing_user: bool = False
    ) -> tuple[str, bool]:
        """`create_user` off the event loop."""
        return await _in_thread(
            self.create_user, user_data, allow_existing_user=allow_existing_user
        )

    async def ainvite_user(
        self,
        user_id: str,
        actions: list[str] | None = None,
        lifespan: int = INVITE_LIFESPAN,
    ) -> bool:
        """`invite_user` off the event loop."""
        return await _in_thread(self.invite_user, user_id, actions, lifespan)

    async def aupdate_user(self, user_id: str, update_data: KeycloakUserUpdate) -> None:
        """`update_user` off the event loop."""
        await _in_thread(self.update_user, user_id, update_data)

    async def adelete_user(
        self, user_id: str, attempts: int = 3, delay: float = 1.0
    ) -> bool:
        """
        `delete_user` off the event loop, with retries (the wait grows: `delay`, then
        twice `delay`, and so on). It never raises. When every attempt fails it logs at
        CRITICAL level, because the account is still usable in Keycloak and has to be
        removed by hand.
        """
        for attempt in range(1, attempts + 1):
            if await _in_thread(self.delete_user, user_id):
                return True
            if attempt < attempts:
                await asyncio.sleep(delay * attempt)

        logger.critical(
            f"Keycloak user {user_id} was NOT deleted after {attempts} attempts: "
            "delete it by hand"
        )
        return False

    def get_user_by_id(self, user_id: str) -> dict:
        """Fetches a user from Keycloak by UUID. Raises NotFoundError if missing."""
        try:
            user = self.admin.get_user(user_id=user_id)
            if not user:
                raise NotFoundError(f"User with ID {user_id} not found in Keycloak")
            return user
        except KeycloakGetError as e:
            if e.response_code == 404:
                raise NotFoundError(
                    f"User with ID {user_id} not found in Keycloak"
                ) from e
            logger.error(
                f"Keycloak API error fetching user {user_id} (HTTP {e.response_code})"
            )
            raise AtsigError("Keycloak API error.") from None
        except Exception as e:
            if isinstance(e, NotFoundError):
                raise e
            logger.error(
                f"Unexpected error fetching user {user_id}: {type(e).__name__}"
            )
            raise AtsigError("Unexpected error fetching the Keycloak user.") from None

    async def get_user_by_id_with_retry(
        self, user_id: str, retries: int = 3, delay: float = 0.2
    ) -> dict | None:
        for attempt in range(retries):
            try:
                user = await _in_thread(self.get_user_by_id, user_id)
                if user:
                    return user
            except NotFoundError:
                logger.warning(
                    f"[KeycloakService] Attempt {attempt + 1}/{retries} - User {user_id} not found yet. Retrying..."
                )
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
            except Exception as e:
                logger.error(
                    f"[KeycloakService] Attempt {attempt + 1}/{retries} failed with unexpected error: {type(e).__name__}"
                )
                if attempt < retries - 1:
                    await asyncio.sleep(delay)

        logger.error(
            f"[KeycloakService] Max retries reached. Could not fetch user {user_id}"
        )
        return None


class NewIdentityTracker:
    """
    Remembers the Keycloak accounts that ONE request created, so that a failure later
    in the request (the local profile, the commit) removes exactly those and never an
    account that existed before. A service creates one per request and calls
    `track` after `acreate_user` (when `is_new`), `discard` when a single profile
    fails, and `commit_or_discard` instead of `session.commit()`.
    """

    def __init__(self, kc_service: KeycloakUserService):
        self.kc_service = kc_service
        self.new_ids: list[str] = []

    def track(self, user_id: str) -> None:
        self.new_ids.append(user_id)

    async def discard(self, user_id: str) -> None:
        """Deletes the account if (and only if) this request created it."""
        if user_id in self.new_ids:
            self.new_ids.remove(user_id)
            await self.kc_service.adelete_user(user_id)

    async def discard_all(self) -> None:
        for user_id in list(self.new_ids):
            await self.discard(user_id)

    async def commit_or_discard(self, session) -> None:
        """Commits the session; when that fails, removes the new accounts and re-raises."""
        try:
            await session.commit()
        except Exception:
            await self.discard_all()
            raise
        self.new_ids.clear()
