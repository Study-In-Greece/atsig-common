from sqlalchemy import Column, Integer, DateTime, func
from sqlalchemy.orm import declared_attr
from sqlalchemy.ext.declarative import cast


class TimestampMixin:
    """Mixin για created_at και updated_at"""

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
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
