from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """Mixin for created_at and updated_at using Mapped"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),  # Αντίστοιχο του default
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )


class IDMixin:
    """Mixin for Primary Key using Mapped"""

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )
