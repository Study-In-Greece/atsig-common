from sqlalchemy import Column, Integer, DateTime, func
from sqlalchemy.orm import declared_attr


class TimestampMixin:
    """Mixin για created_at και updated_at"""

    created_at = Column(
        DateTime(timezone=True),
        default=func.now(),  # Python-side default (Safe-guard)
        server_default=func.now(),  # Database-side default
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),  # Python-side default
        server_default=func.now(),  # Database-side default
        onupdate=func.now(),  # Refreshes on every update
        nullable=False,
    )


class IDMixin:
    """Mixin για το Primary Key"""

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
        nullable=False,
    )
