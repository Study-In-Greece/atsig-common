from sqlalchemy import select, func, asc, desc
from sqlalchemy.ext.asyncio import AsyncSession
from .schemas import PaginationParams, PaginatedResponse


def build_paginated_response(
        pagination: PaginationParams, total: int, items: list
) -> PaginatedResponse:
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
        query,
        model,
        session: AsyncSession,
        pagination: PaginationParams,
        default_sort: str = "id",
        default_order: str = "asc",
):
    """Returns data and total count with dynamic sorting"""
    # 1. Get Total Count
    total = (
            await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    )

    # 2. Handle Dynamic Sorting
    sort_attr = pagination.sort or default_sort
    order_type = pagination.order or default_order

    sort_column = getattr(model, sort_attr, None)

    # Αν το πεδίο sort δεν υπάρχει στο μοντέλο, πέφτουμε στο default_sort (συνήθως id)
    if sort_column is None:
        sort_column = getattr(model, default_sort)
        order_type = default_order

    # Εφαρμογή sorting
    order_func = asc if order_type == "asc" else desc
    query = query.order_by(order_func(sort_column))

    # Προσθήκη δευτερεύοντος sorting για σταθερά αποτελέσματα (Deterministic)
    if sort_attr != "id" and hasattr(model, "id"):
        query = query.order_by(desc(model.id))

    # 3. Apply Limit/Offset
    query = query.offset(pagination.offset).limit(pagination.limit)
    results = (await session.execute(query)).scalars().all()

    return results, total


async def paginate_query(
        query,
        model,
        session: AsyncSession,
        pagination: PaginationParams,
        default_sort: str = "id",
        default_order: str = "asc",
):
    results, total = await paginate_raw(
        query, model, session, pagination, default_sort, default_order
    )
    return build_paginated_response(pagination, total, results)
