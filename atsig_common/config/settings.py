from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


def _url_user(value: str) -> str:
    """
    A user name for a URL. Only what breaks the URL is escaped (`%` first), so a name
    that works as it is stays exactly the same.
    """
    for char, escaped in (("%", "%25"), ("@", "%40"), (":", "%3A"), ("/", "%2F")):
        value = value.replace(char, escaped)
    return value


def _url_password(value: str) -> str:
    """A password for a URL: same rule, only `%` and `@` break it."""
    return value.replace("%", "%25").replace("@", "%40")


class BaseAtsigSettings(BaseSettings):
    # --- 1. GENERAL / MONITORING ---
    ENVIRONMENT: str = "development"
    GLITCHTIP_DSN: str | None = None
    ROOT_PATH: str = ""
    DOCS_URL: str = "/docs"
    REDOC_URL: str = "/redoc"
    ATSIG_HOST_URL: str | None = None
    # Origins the browsers may call the API from ("*" keeps the behaviour of today).
    # In the environment it is a JSON list: CORS_ORIGINS=["https://a.gr","https://b.gr"]
    CORS_ORIGINS: list[str] = ["*"]
    # The email of the user on every log line (and in Sentry). Turn it off to keep
    # personal data out of the logs: the user id is still written.
    LOG_USER_EMAIL: bool = True

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
    # Optional checks of the access token, OFF by default (None). Turn them on only
    # after trying them in a dev realm: a wrong value rejects every user.
    # Issuer: the public address of the realm, e.g. https://sso.example.gr/realms/x
    KEYCLOAK_EXPECTED_ISSUER: str | None = None
    # Audience: needs an audience mapper on the Keycloak client, otherwise tokens
    # carry `aud: account`.
    KEYCLOAK_EXPECTED_AUDIENCE: str | None = None

    # --- 4. REDIS (Optional for shared base) ---
    REDIS_SERVER: str | None = None
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None

    # --- 5. STORAGE (Cloudflare R2 / S3) ---
    R2_ENDPOINT_URL: str
    R2_ACCESS_KEY_ID: str
    R2_SECRET_ACCESS_KEY: str
    R2_PRIVATE_BUCKET: str | None = None
    R2_PUBLIC_BUCKET: str | None = None
    R2_PUBLIC_DOMAIN: str | None = None

    # --- COMPUTED PROPERTIES ---
    @property
    def keycloak_base(self) -> str:
        return f"{self.AUTHORIZATION_URL}/realms/{self.KEYCLOAK_REALM}/protocol/openid-connect"

    @property
    def database_url(self) -> str:
        """
        The URL of the database for SQLAlchemy. A user name or password with a
        character that has a meaning in a URL (`@`, `%`) is escaped; the engine
        decodes it back. Credentials that need no escaping are unchanged.
        """
        return (
            f"postgresql+asyncpg://{_url_user(self.POSTGRES_USER)}"
            f":{_url_password(self.POSTGRES_PASSWORD)}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def alembic_database_url(self) -> str:
        """
        `database_url` for `config.set_main_option("sqlalchemy.url", ...)` in
        Alembic's env.py. That value goes through configparser, where every `%`
        must be written `%%`. Without this, an escaped credential breaks the
        migrations with an interpolation error.
        """
        return self.database_url.replace("%", "%%")

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            safe_password = quote(self.REDIS_PASSWORD)
            return f"redis://:{safe_password}@{self.REDIS_SERVER}:{self.REDIS_PORT}/0"
        return f"redis://{self.REDIS_SERVER}:{self.REDIS_PORT}/0"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )
