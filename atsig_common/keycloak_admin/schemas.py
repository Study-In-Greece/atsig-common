from pydantic import BaseModel, EmailStr, Field


class KeycloakUserCreate(BaseModel):
    """
    A user to create in Keycloak. There is deliberately no password: the user sets
    one from the link of the invitation email (`KeycloakUserService.ainvite_user`).
    """

    username: str
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool = True
    group_path: str
    attributes: dict[str, list[str]] = Field(default_factory=dict)


class KeycloakUserUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool | None = None
    attributes: dict[str, list[str]] | None = None
