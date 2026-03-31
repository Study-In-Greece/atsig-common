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
    """
    The fundamental base service.

    Provides direct access to the database session without any
    authentication or authorization logic.
    """

    def __init__(self, session: AsyncSession):
        """
        Initializes the service with a database session.

        Args:
            session (AsyncSession): The SQLAlchemy async session.
        """
        self.session = session


class CRUDBaseService(
    BaseService, Generic[ModelType, CreateSchemaType, UpdateSchemaType]
):
    """
    A generic Database CRUD engine.

    Provides standard Create, Read, Update, and Delete operations for a
    given SQLAlchemy model, using Pydantic schemas for data validation.
    """

    def __init__(self, model: Type[ModelType], session: AsyncSession):
        """
        Initializes the CRUD service for a specific model.

        Args:
            model (Type[ModelType]): The SQLAlchemy model class.
            session (AsyncSession): The database session.
        """
        super().__init__(session)
        self.model = model

    async def get_or_404(self, resource_id: Any) -> ModelType:
        """
        Retrieves a record or raises a 404 exception.

        Args:
            resource_id (Any): The primary key of the resource.

        Returns:
            ModelType: The retrieved database object.

        Raises:
            NotFoundError: If the object does not exist in the database.
        """
        obj = await self.get(resource_id)
        if not obj:
            raise NotFoundError(f"{self.model.__name__} not found")
        return obj

    async def get(self, resource_id: Any) -> Optional[ModelType]:
        """Fetches a single record by its primary key."""
        return await self.session.get(self.model, resource_id)

    async def get_multi(
        self,
        *,
        query=None,
        pagination: PaginationParams,
        sort_model: Type[ModelType] = None,
    ) -> PaginatedResponse:
        """
        Fetches multiple records with pagination and optional sorting.

        Args:
            query: An optional SQLAlchemy query. Defaults to 'select(model)'.
            pagination (PaginationParams): Pagination and sorting parameters.
            sort_model (Type[ModelType]): Alternative model for sorting.

        Returns:
            PaginatedResponse: Standardized paginated data.
        """
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
        Creates a new database record.

        Args:
            obj_in: Pydantic schema or dict containing the data.
            exclude (set[str]): Fields to exclude from the input data.
            **extra_data: Additional fields to be merged into the object (e.g., owner_id).

        Returns:
            ModelType: The created database object.
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
        Updates an existing database record.

        Args:
            db_obj (ModelType): The current database object.
            obj_in: Pydantic schema or dict with updated values.
            exclude (set[str]): Fields to exclude from the update.

        Returns:
            ModelType: The updated and refreshed database object.
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
        """
        Combines fetch and update in a single operation.

        Ideal for simpler API calls where the object is updated via ID.
        """
        db_obj = await self.get_or_404(resource_id)
        return await self.update(db_obj=db_obj, obj_in=obj_in, exclude=exclude)

    async def remove(self, *, resource_id: Any) -> None:
        """
        Deletes a record from the database.

        Args:
            resource_id (Any): The primary key of the resource to remove.
        """
        db_obj = await self.get_or_404(resource_id)
        await self.session.delete(db_obj)

    async def get_all(self) -> List[ModelType]:
        """Fetches all objects of the model without pagination."""
        query = select(self.model)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_ids(self, resource_ids: List[Any]) -> List[ModelType]:
        """Fetches multiple objects filtering by a list of IDs."""
        query = select(self.model).where(self.model.id.in_(resource_ids))
        result = await self.session.execute(query)
        return list(result.scalars().all())


class BaseAuthService(BaseService, Generic[PolicyType]):
    """
    Base service that integrates with an Authorization Policy.

    This service requires a Policy instance to handle permission checks.
    """

    def __init__(self, session: AsyncSession, policy: Optional[PolicyType] = None):
        """
        Initializes the service with DB session and Auth Policy.

        Args:
            session (AsyncSession): The database session.
            policy (PolicyType): The access policy containing the user context.
        """
        super().__init__(session)
        self.policy: PolicyType = policy
        self.ctx = policy.ctx if policy else None


class CRUDBaseAuthService(
    CRUDBaseService[ModelType, CreateSchemaType, UpdateSchemaType],
    Generic[ModelType, CreateSchemaType, UpdateSchemaType, PolicyType],
):
    """
    A service that combines CRUD capabilities with Authorization Policies.

    Used when operations need to verify if a user has the right to access
    or modify specific database records.
    """

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
        """
        Fetches a resource and performs an authorization check.

        Args:
            resource_id (Any): The primary key.
            check_callback: A function that takes the object and the policy
                to determine if access is granted.

        Returns:
            ModelType: The authorized database object.

        Raises:
            ForbiddenError: If the check_callback returns False.
        """
        db_obj = await self.get_or_404(resource_id)

        if self.policy:
            if not check_callback(db_obj, self.policy):
                raise ForbiddenError("You are not authorized to perform this action")

        return db_obj
