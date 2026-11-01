from atsig_common.db.engine import create_db_engine, create_session_factory

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
