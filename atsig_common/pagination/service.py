from typing import Optional, Type, Any

from sqlalchemy import select, func, asc, desc
from sqlalchemy.ext.asyncio import AsyncSession
from .schemas import PaginationParams, PaginatedResponse


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
    model: Type[Any],
    session: AsyncSession,
    pagination: PaginationParams,
    sort_model: Optional[Type[Any]] = None,
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
    sort_column = getattr(effective_sort_model, sort_attr, None)

    # Fallback to the primary model if a sort_model was provided but the attribute was missing
    if sort_column is None and sort_model is not None:
        sort_column = getattr(model, sort_attr, None)

    # If the attribute is still not found (e.g., invalid string), fallback to 'id' or 'created_at'
    if sort_column is None:
        sort_attr = "id"  # Reset attribute name for the deterministic check below
        sort_column = getattr(model, "id", None) or getattr(model, "created_at", None)

    # 3. Apply Sorting
    order_func = asc if order_type == "asc" else desc

    if sort_column is not None:
        query = query.order_by(order_func(sort_column))

        # Apply Secondary Sorting (Deterministic Result Set)
        # We add a secondary sort key if the primary key is not already 'id' or 'created_at'.
        # This prevents inconsistent ordering when the primary sort column has duplicate values.
        if sort_attr not in ["id", "created_at"]:
            secondary_col = getattr(model, "id", None) or getattr(
                model, "created_at", None
            )
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
    sort_model: Optional[Type[Any]] = None,
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
