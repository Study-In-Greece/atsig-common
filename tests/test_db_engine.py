from atsig_common.db.engine import (
    create_db_engine,
    create_db_engine_from_settings,
    create_session_factory,
)

URL = "postgresql+asyncpg://user:secret@localhost:5432/db"


def test_defaults_are_the_ones_of_the_services_plus_hidden_parameters():
    engine = create_db_engine(URL)

    assert engine.pool.size() == 10
    assert engine.pool._max_overflow == 20
    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 3600
    assert engine.sync_engine.hide_parameters is True


def test_any_option_can_be_overridden():
    engine = create_db_engine(URL, pool_size=2, max_overflow=3, hide_parameters=False)

    assert engine.pool.size() == 2
    assert engine.pool._max_overflow == 3
    assert engine.sync_engine.hide_parameters is False


def test_session_factory_keeps_attributes_after_commit_by_default():
    engine = create_db_engine(URL)

    assert create_session_factory(engine).kw["expire_on_commit"] is False
    assert create_session_factory(engine, expire_on_commit=True).kw["expire_on_commit"]


class _Settings:
    database_url = URL


def test_the_pool_is_read_from_the_settings():
    settings = _Settings()
    settings.DB_POOL_SIZE = 5
    settings.DB_MAX_OVERFLOW = 7

    engine = create_db_engine_from_settings(settings)

    assert engine.pool.size() == 5
    assert engine.pool._max_overflow == 7
    assert engine.sync_engine.hide_parameters is True


def test_settings_without_the_pool_fields_get_the_default_pool():
    engine = create_db_engine_from_settings(_Settings())

    assert engine.pool.size() == 10
    assert engine.pool._max_overflow == 20


def test_a_keyword_beats_the_settings():
    settings = _Settings()
    settings.DB_POOL_SIZE = 5
    settings.DB_MAX_OVERFLOW = 7

    engine = create_db_engine_from_settings(settings, pool_size=2)

    assert engine.pool.size() == 2
    assert engine.pool._max_overflow == 7


def test_the_base_settings_have_the_default_pool(monkeypatch):
    from atsig_common.config.settings import BaseAtsigSettings

    for name, value in {
        "POSTGRES_USER": "u",
        "POSTGRES_PASSWORD": "p",
        "POSTGRES_SERVER": "h",
        "POSTGRES_DB": "d",
        "KEYCLOAK_REALM": "r",
        "KEYCLOAK_CLIENT_ID": "c",
        "KEYCLOAK_CLIENT_SECRET": "s",
        "AUTHORIZATION_URL": "http://k",
        "R2_ENDPOINT_URL": "http://r2",
        "R2_ACCESS_KEY_ID": "a",
        "R2_SECRET_ACCESS_KEY": "s",
    }.items():
        monkeypatch.setenv(name, value)

    settings = BaseAtsigSettings(_env_file=None)
    assert (settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW) == (10, 20)

    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "5")
    settings = BaseAtsigSettings(_env_file=None)
    assert create_db_engine_from_settings(settings).pool.size() == 5
