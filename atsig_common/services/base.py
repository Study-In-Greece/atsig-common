from sqlalchemy import select
from typing import Optional, TypeVar, Generic, Any, Type, Union, Dict, List, Callable

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import BaseAccessPolicy
from ..exceptions import NotFoundError, ForbiddenError
from ..pagination import PaginationParams, PaginatedResponse, paginate_query

ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)
PolicyType = TypeVar("PolicyType", bound=BaseAccessPolicy)


class BaseService:
    """The ultimate base: DB, no Auth"""

    def __init__(self, session: AsyncSession):
        self.session = session


class CRUDBaseService(
    BaseService, Generic[ModelType, CreateSchemaType, UpdateSchemaType]
):
    """The pure Database CRUD engine"""

    def __init__(self, model: Type[ModelType], session: AsyncSession):
        super().__init__(session)
        self.model = model

    async def _get_or_404(self, resource_id: Any) -> ModelType:
        """Helper for fetch with 404, without auth check"""
        obj = await self.session.get(self.model, resource_id)
        if not obj:
            raise NotFoundError(f"{self.model.__name__} not found")
        return obj

    async def get(self, resource_id: Any) -> Optional[ModelType]:
        return await self.session.get(self.model, resource_id)

    async def get_multi(
        self,
        *,
        query=None,
        pagination: PaginationParams,
        sort_model: Type[ModelType] = None,
    ) -> PaginatedResponse:
        if query is None:
            query = select(self.model)
        return await paginate_query(
            query, self.model, self.session, pagination, sort_model=sort_model
        )

    async def create(
        self,
        *,
        obj_in: Union[CreateSchemaType, dict[str, Any]],
        exclude: Optional[set[str]] = None,
        **extra_data: Any,
    ) -> ModelType:
        """
        Creates a new record, allowing exclusion of non-model fields.
        """
        if isinstance(obj_in, dict):
            data = obj_in
        else:
            data = obj_in.model_dump(exclude=exclude)

        final_data = {**data, **extra_data}

        db_obj = self.model(**final_data)
        self.session.add(db_obj)

        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    async def update(
        self,
        *,
        db_obj: ModelType,
        obj_in: Union[UpdateSchemaType, Dict[str, Any]],
        exclude: Optional[set[str]] = None,
    ) -> ModelType:
        """
        Updates a record, allowing exclusion of non-model fields.
        """
        if isinstance(obj_in, dict):
            update_data = obj_in
            if exclude:
                for field in exclude:
                    update_data.pop(field, None)
        else:
            update_data = obj_in.model_dump(exclude_unset=True, exclude=exclude)

        for field in update_data:
            if hasattr(db_obj, field):
                setattr(db_obj, field, update_data[field])

        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    async def find_and_update(
        self,
        resource_id: Any,
        obj_in: Union[UpdateSchemaType, Dict[str, Any]],
        exclude: Optional[set[str]] = None,
    ) -> ModelType:
        """Fetch and Update in one call (ideal for Uni API)"""
        db_obj = await self._get_or_404(resource_id)
        return await self.update(db_obj=db_obj, obj_in=obj_in, exclude=exclude)

    async def remove(self, *, resource_id: Any) -> None:
        db_obj = await self._get_or_404(resource_id)
        await self.session.delete(db_obj)

    async def get_all(self) -> List[ModelType]:
        """Fetch all objects without pagination."""
        query = select(self.model)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_ids(self, resource_ids: List[Any]) -> List[ModelType]:
        """Fetch multiple objects based on a list of IDs."""
        query = select(self.model).where(self.model.id.in_(resource_ids))
        result = await self.session.execute(query)
        return list(result.scalars().all())


class BaseAuthService(BaseService, Generic[PolicyType]):
    """Requires Strict Auth Policy"""

    def __init__(self, session: AsyncSession, policy: Optional[PolicyType] = None):
        super().__init__(session)
        self.policy: PolicyType = policy
        self.ctx = policy.ctx if policy else None


class CRUDBaseAuthService(
    CRUDBaseService[ModelType, CreateSchemaType, UpdateSchemaType],
    Generic[ModelType, CreateSchemaType, UpdateSchemaType, PolicyType],
):
    """CRUD + Auth Policy"""

    def __init__(
        self,
        model: Type[ModelType],
        session: AsyncSession,
        policy: Optional[PolicyType] = None,
    ):
        super().__init__(model, session)
        self.policy = policy
        self.ctx = policy.ctx if policy else None

    async def get_authorized(
        self, resource_id: Any, check_callback: Callable[[ModelType, PolicyType], None]
    ) -> ModelType:
        db_obj = await self._get_or_404(resource_id)

        if self.policy:
            if not check_callback(db_obj, self.policy):
                raise ForbiddenError("You are not authorized to perform this action")

        return db_obj
