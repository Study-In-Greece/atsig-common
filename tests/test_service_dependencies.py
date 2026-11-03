import inspect
from types import SimpleNamespace
from typing import get_type_hints

from atsig_common.email.client import AsyncEmailClient
from atsig_common.email.dependencies import make_get_email_client
from atsig_common.redis.dependencies import make_get_event_producer
from atsig_common.redis.producer import EventProducer
from atsig_common.services.factory import make_service_factory


def test_the_email_client_is_one_per_process_and_uses_the_redis_url():
    get_email_client = make_get_email_client(SimpleNamespace(redis_url="redis://r/0"))

    client = get_email_client()

    assert isinstance(client, AsyncEmailClient)
    assert get_email_client() is client


def test_the_event_producer_is_one_per_process_with_its_options(fake_redis):
    get_event_producer = make_get_event_producer(
        fake_redis, default_maxlen=100, default_retries=2
    )

    producer = get_event_producer()

    assert isinstance(producer, EventProducer)
    assert producer.redis_manager is fake_redis
    assert (producer.default_maxlen, producer.default_retries) == (100, 2)
    assert get_event_producer() is producer


def test_the_return_types_are_there_for_the_service_factory(fake_redis):
    get_email_client = make_get_email_client(SimpleNamespace(redis_url="redis://r/0"))
    get_event_producer = make_get_event_producer(fake_redis)
    assert get_type_hints(get_email_client)["return"] is AsyncEmailClient
    assert get_type_hints(get_event_producer)["return"] is EventProducer

    get_service = make_service_factory(
        get_session=lambda: None,
        email_client=get_email_client,
        producer=get_event_producer,
    )

    class Service:
        def __init__(self, session, email_client, producer):
            pass

    parameters = inspect.signature(
        get_service(Service, extra=["email_client", "producer"])
    ).parameters
    assert parameters["email_client"].annotation is AsyncEmailClient
    assert parameters["producer"].annotation is EventProducer
