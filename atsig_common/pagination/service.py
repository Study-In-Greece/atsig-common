from typing import Any

from sqlalchemy import asc, desc, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.hybrid import hybrid_property

from ..logger.config import get_logger
from .schemas import PaginatedResponse, PaginationParams

logger = get_logger("atsig_common.pagination")


def sortable_names(model: Any) -> frozenset[str]:
    """
    Names a list may be sorted by: the mapped columns of the model and its hybrid
    properties. Relationships, plain properties, methods and everything else on the
    class (`metadata`, `registry`, `__class__`, ...) are not sortable.
    """
    mapper = getattr(sa_inspect(model, raiseerr=False), "mapper", None)
    if mapper is None:
        return frozenset()

    names = set(mapper.column_attrs.keys())
    names.update(
        name
        for name, descriptor in mapper.all_orm_descriptors.items()
        if isinstance(descriptor, hybrid_property)
    )
    return frozenset(names)


def _sort_column(model: Any, name: str | None) -> Any | None:
    """The attribute to ORDER BY for `name`, or None when the model cannot sort by it."""
    if not isinstance(name, str) or name not in sortable_names(model):
        return None
    return getattr(model, name, None)


def build_paginated_response(
    pagination: PaginationParams, total: int, items: list
) -> PaginatedResponse:
    """
    Constructs a PaginatedResponse object with metadata.

    Args:
        pagination (PaginationParams): The pagination settings (page, limit, offset).
        total (int): The total count of records in the database.
        items (list): The list of items for the current page.

    Returns:
        PaginatedResponse: A standardized response object containing data and metadata.
    """
    # Calculate total pages, ensuring at least 0 if no records exist
    total_pages = (total + pagination.limit - 1) // pagination.limit if total > 0 else 0
    return PaginatedResponse(
        total=total,
        page=pagination.page,
        limit=pagination.limit,
        items=items,
        has_next=pagination.offset + pagination.limit < total,
        has_previous=pagination.page > 1,
        total_pages=total_pages,
    )


async def paginate_raw(
    query: Any,
    model: type[Any],
    session: AsyncSession,
    pagination: PaginationParams,
    sort_model: type[Any] | None = None,
    default_sort: str = "id",
    default_order: str = "asc",
):
    """
    Executes a paginated query with dynamic sorting and reliable fallbacks.

    This function handles the database-level operations: counting total records,
    applying dynamic sorting based on provided attributes, and fetching the
    requested slice of data.

    Returns:
        tuple: A tuple containing (results, total_count).
    """

    # 1. Get Total Count using a subquery to handle complex joins/filters correctly
    total = (
        await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    )

    # 2. Handle Dynamic Sorting
    sort_attr = pagination.sort or default_sort
    order_type = pagination.order or default_order
    effective_sort_model = sort_model or model

    # Attempt to find the sorting column in the specified model
    sort_column = _sort_column(effective_sort_model, sort_attr)

    # Fallback to the primary model if a sort_model was provided but the attribute was missing
    if sort_column is None and sort_model is not None:
        sort_column = _sort_column(model, sort_attr)

    if sort_column is None and pagination.sort:
        # Not something the model can sort by: the default order applies. Only the
        # size and the start of what the caller sent are logged.
        logger.warning(
            f"Ignored an unknown sort field of {len(pagination.sort)} characters: "
            f"{pagination.sort[:20]!r}"
        )

    # If the attribute is still not found (e.g., invalid string), fallback to 'id' or 'created_at'
    if sort_column is None:
        sort_attr = "id"  # Reset attribute name for the deterministic check below
        sort_column = _sort_column(model, "id")
        if sort_column is None:
            sort_column = _sort_column(model, "created_at")

    # 3. Apply Sorting
    order_func = asc if order_type == "asc" else desc

    if sort_column is not None:
        query = query.order_by(order_func(sort_column))

        # Apply Secondary Sorting (Deterministic Result Set)
        # We add a secondary sort key if the primary key is not already 'id' or 'created_at'.
        # This prevents inconsistent ordering when the primary sort column has duplicate values.
        if sort_attr not in ["id", "created_at"]:
            secondary_col = _sort_column(model, "id")
            if secondary_col is None:
                secondary_col = _sort_column(model, "created_at")
            if secondary_col is not None:
                query = query.order_by(desc(secondary_col))
    else:
        # If all sorting attempts fail, proceed without specific ordering
        pass

    # 4. Apply Limit/Offset
    query = query.offset(pagination.offset).limit(pagination.limit)
    results = (await session.execute(query)).scalars().all()

    return results, total


async def paginate_query(
    query,
    model,
    session: AsyncSession,
    pagination: PaginationParams,
    sort_model: type[Any] | None = None,
    default_sort: str = "id",
    default_order: str = "asc",
):
    """
    Higher-level utility that paginates a query and returns a formatted response.

    Args:
        query: The SQLAlchemy query object.
        model: The primary SQLAlchemy model class.
        session (AsyncSession): The database session.
        pagination (PaginationParams): The requested pagination parameters.
        sort_model (Optional[Type[Any]]): Alternative model for sorting (useful for joins).
        default_sort (str): Default column to sort by.
        default_order (str): Default sort direction ("asc" or "desc").

    Returns:
        PaginatedResponse: The final response object ready to be returned by an API.
    """
    results, total = await paginate_raw(
        query, model, session, pagination, sort_model, default_sort, default_order
    )
    return build_paginated_response(pagination, total, results)
