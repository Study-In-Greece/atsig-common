import logging

import pytest
from sqlalchemy import String, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from atsig_common.pagination import PaginationParams
from atsig_common.pagination.service import paginate_raw, sortable_names


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "owner"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String)


class Item(Base):
    __tablename__ = "item"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_id: Mapped[int] = mapped_column()
    owner: Mapped[Owner] = relationship(
        "Owner", primaryjoin="Item.owner_id == Owner.id", foreign_keys=[owner_id]
    )

    @hybrid_property
    def is_agent_submission(self) -> bool:
        return self.agent_id is not None

    @is_agent_submission.expression
    def is_agent_submission(cls):
        return cls.agent_id.is_not(None)

    @property
    def display(self):
        return self.name


class FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class FakeSession:
    def __init__(self):
        self.query = None

    async def scalar(self, _statement):
        return 0

    async def execute(self, statement):
        self.query = statement
        return FakeResult()


async def order_by_sql(sort, order="asc", **kwargs) -> str:
    session = FakeSession()
    await paginate_raw(
        select(Item),
        Item,
        session,
        PaginationParams(sort=sort, order=order),
        **kwargs,
    )
    sql = str(session.query.compile(dialect=postgresql.dialect()))
    return sql.split("ORDER BY", 1)[1].split("LIMIT", 1)[0].strip()


def test_only_columns_and_hybrids_are_sortable():
    names = sortable_names(Item)

    assert names == {"id", "name", "agent_id", "owner_id", "is_agent_submission"}


@pytest.mark.parametrize(
    "bad",
    ["metadata", "registry", "__class__", "__tablename__", "display", "owner", "nope"],
)
async def test_unsortable_name_falls_back_to_id_with_a_warning(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="atsig_common.pagination"):
        sql = await order_by_sql(bad)

    assert sql == "item.id ASC"
    assert "Ignored an unknown sort field" in caplog.text


async def test_column_sort_adds_the_id_tiebreaker():
    assert await order_by_sql("name", "desc") == "item.name DESC, item.id DESC"


async def test_hybrid_property_is_sortable():
    sql = await order_by_sql("is_agent_submission")

    assert sql.startswith("item.agent_id IS NOT NULL ASC")


async def test_sort_model_is_used_first_then_the_primary_model():
    assert (
        await order_by_sql("full_name", sort_model=Owner)
        == "owner.full_name ASC, item.id DESC"
    )
    assert await order_by_sql("name", sort_model=Owner) == "item.name ASC, item.id DESC"


async def test_default_sort_none_without_a_requested_sort_uses_id():
    assert await order_by_sql(None, default_sort=None) == "item.id ASC"
