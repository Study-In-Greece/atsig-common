import logging

from atsig_common.redis.consumer import BaseRedisConsumer

SECRET = "someone@example.com"


class FailingConsumer(BaseRedisConsumer):
    def __init__(self, redis_manager, **kwargs):
        super().__init__(
            redis_manager,
            stream_name="events",
            group_name="group",
            retry_delay=0,
            **kwargs,
        )
        self.attempts = 0

    async def process_message(self, message_id, action, payload):
        self.attempts += 1
        raise RuntimeError(f"INSERT failed, parameters: {{'email': '{SECRET}'}}")


async def test_dlq_error_holds_only_the_exception_type(fake_redis, caplog):
    consumer = FailingConsumer(fake_redis)

    with caplog.at_level(logging.DEBUG):
        await consumer._handle_message("1-0", {"action": "sync", "data": "{}"})

    assert consumer.attempts == 3
    (xadd,) = fake_redis.commands("xadd")
    assert xadd[2]["error"] == "RuntimeError"
    assert SECRET not in caplog.text
    assert len(fake_redis.commands("xack")) == 1


async def test_failed_dlq_write_logs_only_the_exception_type(fake_redis, caplog):
    fake_redis.fail_xadd = True
    consumer = FailingConsumer(fake_redis)

    with caplog.at_level(logging.DEBUG):
        await consumer._handle_message("1-0", {"action": "sync", "data": "{}"})

    assert "ConnectionError" in caplog.text
    assert SECRET not in caplog.text
