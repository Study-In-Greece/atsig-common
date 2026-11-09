from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

NAME_MAX = 255


class UserBase(BaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None


class UserCreate(UserBase):
    """A user to create in Keycloak and locally. There is no password: Keycloak emails
    the new account the link to set one."""

    first_name: str | None = Field(default=None, max_length=NAME_MAX)
    last_name: str | None = Field(default=None, max_length=NAME_MAX)
    group_path: str


class UserLocalCreate(UserBase):
    group_path: str
    is_active: bool | None = True


class UserRead(UserBase):
    uuid: str
    group_path: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=NAME_MAX)
    last_name: str | None = Field(default=None, max_length=NAME_MAX)
    is_active: bool | None = None
