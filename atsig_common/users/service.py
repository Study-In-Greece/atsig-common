"""
The identity layer of the users, shared by the services that create accounts: the
Keycloak account, the local `user` row (whose uuid IS the id in Keycloak) and the
`user_events` stream.

A service passes its own `User` model (declared with `UserMixin`) and subclasses
this class when it needs more.
"""

import logging
import uuid
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..events import Actions, Streams, UserDeleteEvent, UserSyncEvent
from ..exceptions import ConflictError
from ..keycloak_admin import (
    KeycloakUserCreate,
    KeycloakUserService,
    KeycloakUserUpdate,
    NewIdentityTracker,
)
from ..redis.producer import EventProducer
from ..services.base import CRUDBaseService
from .schemas import UserCreate, UserLocalCreate, UserUpdate

logger = logging.getLogger("user-service")


def _user_sync_payload(user: Any) -> dict:
    """The payload of the user_events sync event (the model is shared with the consumers)."""
    return UserSyncEvent(
        uuid=user.uuid,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
    ).to_payload()


class UserService(CRUDBaseService[Any, UserCreate, UserUpdate]):
    def __init__(
        self,
        user_model: type,
        session: AsyncSession,
        kc_service: KeycloakUserService,
        producer: EventProducer,
    ):
        super().__init__(user_model, session)
        self.kc_service = kc_service
        self.producer = producer
        # The Keycloak users this request created. If the request fails they are removed
        # again (`discard_identity`, `commit`): the uuid of the local user is the id in
        # Keycloak, so the user has to be created there first.
        self._identities = NewIdentityTracker(kc_service)

    async def create_user(
        self,
        background_tasks: BackgroundTasks,
        data: UserCreate,
        attributes: dict = None,
        allow_existing_user: bool = False,
    ) -> Any:
        """
        Creates an Identity in Keycloak and a local User record.
        Includes a compensating transaction for Keycloak if DB flush fails. When the
        route commits, it uses `commit` of this service, which removes the Keycloak user
        also when the commit fails.

        An email that already exists in Keycloak is refused (409) unless
        `allow_existing_user` is True, see KeycloakUserService.create_user.
        """
        attributes = attributes or {}

        kc_data = KeycloakUserCreate(
            **data.model_dump(),
            username=str(data.email),
            enabled=True,
            attributes=attributes,
        )

        kc_user_id, is_new_kc_user = await self.kc_service.acreate_user(
            kc_data, allow_existing_user=allow_existing_user
        )
        if is_new_kc_user:
            self._identities.track(kc_user_id)
        logger.info(f"Keycloak identity resolved: {kc_user_id} (New: {is_new_kc_user})")

        try:
            local_data = UserLocalCreate(
                email=data.email,
                first_name=data.first_name,
                last_name=data.last_name,
                group_path=data.group_path,
                is_active=True,
            )
            new_user = await self.create_local_user_only(
                background_tasks=background_tasks,
                data=local_data,
                user_uuid=kc_user_id,
            )

            self.session.add(new_user)
            await self.session.flush()

            return new_user

        except Exception:
            # Compensating transaction: Keycloak is cleaned ONLY if this request created the user
            if kc_user_id and is_new_kc_user:
                logger.warning(
                    f"DB Failure: Rolling back newly created Keycloak user {kc_user_id}"
                )
                await self.discard_identity(kc_user_id)
            elif not is_new_kc_user:
                logger.warning(
                    f"DB Failure: Keycloak user {kc_user_id} was pre-existing, skipping Keycloak rollback."
                )

            raise

    async def discard_identity(self, kc_user_id: str) -> None:
        """
        Removes from Keycloak a user that THIS request created, after a later step
        failed. A user that existed before the request (`allow_existing_user`) is never
        removed.
        """
        await self._identities.discard(kc_user_id)

    async def commit(self) -> None:
        """
        Commits the session. When the commit fails, the Keycloak users this request
        created are removed, so they do not stay behind without a local record (their
        email would then be refused as already existing).

        After a successful commit each new account gets its invitation email from
        Keycloak (a link to set the password). It is sent only now, so that a failed
        request never leaves a link to an account that was removed. A failed invitation
        is logged and does not fail the request.
        """
        new_ids = list(self._identities.new_ids)
        await self._identities.commit_or_discard(self.session)
        for kc_user_id in new_ids:
            await self.kc_service.ainvite_user(kc_user_id)

    async def update_user(
        self,
        background_tasks: BackgroundTasks,
        user_id: str,
        update_data: UserUpdate,
        attributes: dict | None = None,
    ) -> Any:
        """
        Updates user info in both Keycloak and Local DB.
        """
        db_user = await self.get_or_404(user_id)

        if db_user.is_active:
            # 1. Keycloak Update
            kc_update_payload = KeycloakUserUpdate(
                email=db_user.email,
                first_name=(
                    update_data.first_name
                    if update_data.first_name is not None
                    else db_user.first_name
                ),
                last_name=(
                    update_data.last_name
                    if update_data.last_name is not None
                    else db_user.last_name
                ),
                enabled=(
                    update_data.is_active
                    if update_data.is_active is not None
                    else db_user.is_active
                ),
                attributes=attributes,
            )
            await self.kc_service.aupdate_user(user_id, kc_update_payload)

        # 2. Local DB Sync
        await self.update_local_user_only(
            background_tasks=background_tasks, user_uuid=user_id, data=update_data
        )

        return db_user

    async def delete_user(self, background_tasks: BackgroundTasks, user_id: str):
        """
        Permanently removes the user from the DB now and from Keycloak after the route
        has committed.

        The database goes first: if it refuses (or the commit fails) the user must still
        be able to log in, and a Keycloak user cannot be brought back. The Keycloak
        deletion is a background task, so it runs only when the request succeeded. If it
        fails (retried, then logged at CRITICAL level) the account has to be removed by
        hand.
        """
        db_user = await self.get_or_404(user_id)

        # 1. Local DB Deletion
        await self.session.delete(db_user)
        await self.session.flush()

        # 2. After the commit. The tasks run one after the other and one that raises
        # stops the rest, so Keycloak goes first and the event cannot raise (emit_safe).
        background_tasks.add_task(self.kc_service.adelete_user, user_id)
        background_tasks.add_task(
            self.producer.emit_safe,
            stream_name=Streams.USERS,
            action=Actions.DELETE,
            payload=UserDeleteEvent(uuid=user_id).to_payload(),
        )

    async def sync_local_user(
        self, background_tasks: BackgroundTasks, data: UserLocalCreate, user_uuid: str
    ) -> Any:
        """
        JIT provisioning of local User records from Keycloak tokens.
        """
        user_db = await self.session.get(self.model, user_uuid)

        if not user_db:
            logger.info(f"Creating user from Keycloak: {user_uuid}")
            user_db = await self.create_local_user_only(
                background_tasks=background_tasks, data=data, user_uuid=user_uuid
            )
        else:
            logger.info(f"Updating user from Keycloak: {user_uuid}")
            user_db = await self.update_local_user_only(
                background_tasks=background_tasks,
                data=UserUpdate(first_name=data.first_name, last_name=data.last_name),
                user_uuid=user_uuid,
            )
        return user_db

    async def create_local_user_only(
        self,
        background_tasks: BackgroundTasks,
        data: UserLocalCreate,
        user_uuid: str | None = None,
    ) -> Any:
        """
        Creates a local User record ONLY, without interacting with Keycloak.
        Generates a local UUID for the user.
        """
        existing_user = await self.get_user_by_email(data.email)
        if existing_user:
            raise ConflictError("A user with this email already exists locally.")

        local_uuid = user_uuid or str(uuid.uuid4())

        new_user = self.model(
            **data.model_dump(),
            uuid=local_uuid,
        )
        self.session.add(new_user)
        await self.session.flush()

        background_tasks.add_task(
            self.producer.emit_safe,
            stream_name=Streams.USERS,
            action=Actions.SYNC,
            payload=_user_sync_payload(new_user),
        )

        return new_user

    async def update_local_user_only(
        self,
        background_tasks: BackgroundTasks,
        user_uuid: str,
        data: UserUpdate,
    ) -> Any:
        """
        Updates a local User record ONLY. Used primarily by Keycloak webhooks.
        """
        db_user = await self.get_or_404(user_uuid)

        if data.first_name is not None:
            db_user.first_name = data.first_name
        if data.last_name is not None:
            db_user.last_name = data.last_name
        if data.is_active is not None:
            db_user.is_active = data.is_active

        await self.session.flush()

        background_tasks.add_task(
            self.producer.emit_safe,
            stream_name=Streams.USERS,
            action=Actions.SYNC,
            payload=_user_sync_payload(db_user),
        )

        return db_user

    async def read_users_by_uuids(self, uuids: list[str]) -> list[Any]:
        result = await self.session.execute(
            select(self.model).where(self.model.uuid.in_(uuids))
        )
        return list(result.scalars().all())

    async def get_user_by_email(self, email: str) -> Any | None:
        result = await self.session.execute(
            select(self.model).where(self.model.email == email)
        )
        return result.scalar_one_or_none()
