from typing import Optional, Type, Any

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
    query: Any,
    model: Type[Any],
    session: AsyncSession,
    pagination: PaginationParams,
    sort_model: Optional[Type[Any]] = None,
    default_sort: str = "id",
    default_order: str = "asc",
):
    """Returns data and total count with dynamic sorting and reliable fallbacks."""

    # 1. Get Total Count
    total = (
        await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    )

    # 2. Handle Dynamic Sorting
    sort_attr = pagination.sort or default_sort
    order_type = pagination.order or default_order
    effective_sort_model = sort_model or model

    # Προσπάθεια εύρεσης της στήλης
    sort_column = getattr(effective_sort_model, sort_attr, None)

    # Fallback στο βασικό μοντέλο αν δώσαμε sort_model αλλά δεν βρέθηκε εκεί η στήλη
    if sort_column is None and sort_model is not None:
        sort_column = getattr(model, sort_attr, None)

    # Αν ακόμα δεν βρέθηκε (π.χ. λάθος string στο sort), ψάχνουμε id ή created_at
    if sort_column is None:
        sort_attr = "id"  # Reset το attribute name για το deterministic check παρακάτω
        sort_column = getattr(model, "id", None) or getattr(model, "created_at", None)

    # 3. Εφαρμογή Sorting
    order_func = asc if order_type == "asc" else desc

    if sort_column is not None:
        query = query.order_by(order_func(sort_column))

        # Προσθήκη δευτερεύοντος sorting (Deterministic)
        # Μόνο αν δεν ταξινομούμε ήδη βάσει id/created_at
        if sort_attr not in ["id", "created_at"]:
            secondary_col = getattr(model, "id", None) or getattr(
                model, "created_at", None
            )
            if secondary_col is not None:
                query = query.order_by(desc(secondary_col))
    else:
        # Αν όλα αποτύχουν, μην κρασάρεις, απλώς μην κάνεις sort ή βάλε ένα default
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
    results, total = await paginate_raw(
        query, model, session, pagination, sort_model, default_sort, default_order
    )
    return build_paginated_response(pagination, total, results)
