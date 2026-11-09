from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column


class UserMixin:
    """
    The columns of the `user` table, the same in every service that keeps users: the
    uuid is the id of the account in Keycloak. A service declares

        class User(TimestampBase, UserMixin):
            __tablename__ = "user"
            <its own relationships>

    (`created_at` / `updated_at` come from `TimestampMixin`).
    """

    uuid: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(
        String,
        unique=True,
        index=True,
        nullable=False,
    )
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    group_path: Mapped[str | None] = mapped_column(String, nullable=True)
