from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAtsigSettings(BaseSettings):
    # --- 1. GENERAL / MONITORING ---
    ENVIRONMENT: str = "development"
    GLITCHTIP_DSN: Optional[str] = None
    ROOT_PATH: str = ""
    DOCS_URL: str = "/docs"
    REDOC_URL: str = "/redoc"
    ATSIG_HOST_URL: Optional[str] = None

    # --- 2. DATABASE (Shared Anchors) ---
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str

    # --- 3. AUTH (Keycloak) ---
    KEYCLOAK_REALM: str
    KEYCLOAK_CLIENT_ID: str
    KEYCLOAK_CLIENT_SECRET: str
    AUTHORIZATION_URL: str
    KEYCLOAK_VERIFY_SSL: bool = True

    # --- 4. REDIS (Προαιρετικό για το shared base) ---
    REDIS_SERVER: Optional[str] = None
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None

    # --- 5. MAIL (Προαιρετικό) ---
    MAIL_USERNAME: Optional[str] = None
    MAIL_PASSWORD: Optional[str] = None
    MAIL_FROM: Optional[str] = None
    MAIL_PORT: Optional[int] = 587
    MAIL_SERVER: Optional[str] = None
    MAIL_STARTTLS: bool = True

    # --- COMPUTED PROPERTIES ---
    @property
    def keycloak_base(self) -> str:
        return f"{self.AUTHORIZATION_URL}/realms/{self.KEYCLOAK_REALM}/protocol/openid-connect"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )
