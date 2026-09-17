from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=10, le=1000)
    sort: str | None = None
    order: str | None = Field("asc", pattern="^(asc|desc)$")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


class PaginatedResponse(BaseModel, Generic[T]):
    total: int
    page: int
    limit: int
    items: list[T]
    has_next: bool
    has_previous: bool
    total_pages: int
