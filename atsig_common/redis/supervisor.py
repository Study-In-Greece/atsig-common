"""
The supervisor that every worker process (`python -m app.worker`) used to copy: it runs
its consumers together and makes the process end as soon as one of them does.

    exit_code = await supervise(consumers, stop_requested, logger)

`install_stop_signals` turns SIGTERM/SIGINT into the `stop_requested` event. With a
heartbeat file (`HEARTBEAT_FILE`), `python -m atsig_common.redis.healthcheck` can serve as
the healthcheck of the container.
"""

import asyncio
import logging
import os
import signal
import time

from .consumer import BaseRedisConsumer

# Seconds a consumer gets to finish the messages it is processing when the worker
# stops. Below the 10 s `docker stop` waits before it kills the container.
SHUTDOWN_TIMEOUT = 8

HEARTBEAT_FILE = os.environ.get("CONSUMER_HEARTBEAT_FILE", "/tmp/consumer-heartbeat")
HEARTBEAT_INTERVAL = 10.0
# A consumer whose loop did not turn for this long is not counted as alive. The loop
# turns at least every `block_ms` (5 s) unless it is handling a message, so this must be
# longer than the slowest handler (the SIS consumer takes up to a few minutes).
HEARTBEAT_STALE_AFTER = 300.0


def install_stop_signals(stop_requested: asyncio.Event) -> None:
    """SIGTERM and SIGINT set `stop_requested`."""
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(stop_signal, stop_requested.set)


def _consumers_alive(consumers: dict[str, BaseRedisConsumer]) -> bool:
    now = time.monotonic()
    return all(
        consumer.last_loop_at is not None
        and now - consumer.last_loop_at < HEARTBEAT_STALE_AFTER
        for consumer in consumers.values()
    )


async def _heartbeat(
    consumers: dict[str, BaseRedisConsumer], path: str, logger: logging.Logger
) -> None:
    """Touches `path` every few seconds while EVERY consumer keeps turning its loop."""
    while True:
        if _consumers_alive(consumers):
            try:
                with open(path, "w") as heartbeat:
                    heartbeat.write(str(time.time()))
            except OSError as e:
                logger.warning(f"Could not write the heartbeat: {type(e).__name__}")
        await asyncio.sleep(HEARTBEAT_INTERVAL)


async def supervise(
    consumers: dict[str, BaseRedisConsumer],
    stop_requested: asyncio.Event,
    logger: logging.Logger,
    shutdown_timeout: float = SHUTDOWN_TIMEOUT,
    heartbeat_file: str | None = HEARTBEAT_FILE,
) -> int:
    """
    Runs the consumers until a stop is requested (exit code 0) or one of them ends
    (exit code 1: a consumer is meant to run forever, so an end is a failure the
    orchestrator must see and restart). In both cases the others are stopped and
    given a short time to finish what they are doing.
    """
    tasks = {
        name: asyncio.create_task(consumer.run(), name=name)
        for name, consumer in consumers.items()
    }
    stop_waiter = asyncio.create_task(stop_requested.wait())
    heartbeat = (
        asyncio.create_task(_heartbeat(consumers, heartbeat_file, logger))
        if heartbeat_file
        else None
    )

    try:
        await asyncio.wait(
            [*tasks.values(), stop_waiter], return_when=asyncio.FIRST_COMPLETED
        )

        exit_code = 0
        for name, task in tasks.items():
            if task.done():
                exit_code = 1
                error = None if task.cancelled() else task.exception()
                logger.critical(
                    f"Consumer '{name}' ended: "
                    f"{type(error).__name__ if error else 'it returned'}"
                )
        if exit_code == 0:
            logger.info("Stop requested, shutting the consumers down...")

        for consumer in consumers.values():
            consumer.stop()
        running = [task for task in tasks.values() if not task.done()]
        if running:
            await asyncio.wait(running, timeout=shutdown_timeout)
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        return exit_code
    finally:
        stop_waiter.cancel()
        if heartbeat:
            heartbeat.cancel()
