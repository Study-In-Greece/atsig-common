import configparser

import pytest
from sqlalchemy.engine import make_url

from atsig_common.config.settings import BaseAtsigSettings


def make_settings(user="app", password="secret", server="db", port=5432, name="apps"):
    return BaseAtsigSettings(
        _env_file=None,
        POSTGRES_USER=user,
        POSTGRES_PASSWORD=password,
        POSTGRES_SERVER=server,
        POSTGRES_PORT=port,
        POSTGRES_DB=name,
        KEYCLOAK_REALM="r",
        KEYCLOAK_CLIENT_ID="c",
        KEYCLOAK_CLIENT_SECRET="s",
        AUTHORIZATION_URL="http://kc",
        R2_ENDPOINT_URL="http://r2",
        R2_ACCESS_KEY_ID="k",
        R2_SECRET_ACCESS_KEY="s",
    )


@pytest.mark.parametrize(
    "password", ["secret", "Pa55-w0rd.x_y", "p/a:s?s#w!o$r&d*(1)+,;=", "ΑβΓ"]
)
def test_credentials_that_work_today_give_the_same_url_as_before(password):
    url = make_settings(password=password).database_url

    assert url == f"postgresql+asyncpg://app:{password}@db:5432/apps"


@pytest.mark.parametrize("password", ["p@ss", "100%real", "p%41", "a@b%c@d"])
def test_a_password_with_an_at_sign_or_percent_survives_the_round_trip(password):
    url = make_settings(password=password).database_url

    assert make_url(url).password == password
    assert make_url(url).host == "db"


@pytest.mark.parametrize("user", ["me@work", "dom:user", "dom/user", "100%"])
def test_a_user_name_with_a_special_character_survives_the_round_trip(user):
    url = make_settings(user=user).database_url

    assert make_url(url).username == user
    assert make_url(url).host == "db"


@pytest.mark.parametrize("password", ["secret", "p@ss", "100%real"])
def test_alembic_url_goes_through_configparser_unchanged(password):
    settings = make_settings(password=password)
    config = configparser.ConfigParser()  # what Alembic's Config is built on
    config.add_section("alembic")

    config.set("alembic", "sqlalchemy.url", settings.alembic_database_url)

    assert config.get("alembic", "sqlalchemy.url") == settings.database_url


def test_the_plain_url_would_break_configparser_when_it_holds_a_percent():
    settings = make_settings(password="p@ss")
    config = configparser.ConfigParser()
    config.add_section("alembic")

    with pytest.raises(ValueError):  # InterpolationSyntaxError
        config.set("alembic", "sqlalchemy.url", settings.database_url)
