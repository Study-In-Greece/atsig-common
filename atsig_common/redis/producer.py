import asyncio
import json
from typing import Any

from redis.client import Pipeline

from ..logger.config import get_logger
from ..logger.context import current_request_id
from .manager import RedisManager

logger = get_logger("atsig_common.redis.producer")


class EventProducer:
    """
    A class for standardized event emitting to Redis Streams.

    Args:
        redis_manager: The connection.
        default_maxlen: When set, every stream is trimmed to about this many entries
            on each emit (Redis `MAXLEN ~`). None keeps every entry, forever.
        default_retries: How many more times `emit` tries when Redis fails, unless the
            call says otherwise. 0 (the default) raises at the first failure. A retry
            can publish an event twice, so the consumers must be idempotent.
    """

    def __init__(
        self,
        redis_manager: RedisManager,
        default_maxlen: int | None = None,
        default_retries: int = 0,
    ):
        self.redis_manager = redis_manager
        self.default_maxlen = default_maxlen
        self.default_retries = default_retries

    async def emit(
        self,
        stream_name: str,
        action: str,
        payload: dict[str, Any],
        pipe: RedisManager | Pipeline | None = None,
        *,
        maxlen: int | None = None,
        retries: int | None = None,
        retry_delay: float = 0.2,
    ) -> str:
        """
        Publishes an event to the specified Redis Stream.

        Embeds the action into the payload and serializes it to JSON
        under the "data" key (exactly as our BaseConsumer expects).

        Args:
            pipe: A pipeline to add the command to. Nothing is sent until the
                pipeline is executed, so a pipeline is never retried here.
            maxlen: Trim the stream to about this many entries (default: the
                `default_maxlen` of the producer).
            retries: How many more times to try when Redis fails, waiting
                `retry_delay` seconds, then twice as long, and so on. A retry can
                publish the event twice (the first try may have reached Redis before
                the connection broke), so consumers must be idempotent, as ours are.
        """
        try:
            stream_data = {"action": action, "data": json.dumps(payload, default=str)}
        except Exception as e:
            logger.error(
                f"[Producer] Could not serialize '{action}' for '{stream_name}': "
                f"{type(e).__name__}"
            )
            raise

        # The id of the request that causes the event travels beside the payload, so a
        # consumer can log under the same id. Old consumers ignore the extra field.
        request_id = current_request_id()
        if request_id:
            stream_data["meta"] = json.dumps({"request_id": request_id})

        target = pipe if pipe is not None else self.redis_manager

        options: dict[str, Any] = {}
        limit = maxlen if maxlen is not None else self.default_maxlen
        if limit is not None:
            options = {"maxlen": limit, "approximate": True}

        if retries is None:
            retries = self.default_retries
        attempts = (retries if pipe is None else 0) + 1
        for attempt in range(1, attempts + 1):
            try:
                message_id = await target.xadd(stream_name, stream_data, **options)
                break
            except Exception as e:
                if attempt == attempts:
                    logger.error(
                        f"[Producer] Failed to emit '{action}' to '{stream_name}': "
                        f"{type(e).__name__}"
                    )
                    raise
                logger.warning(
                    f"[Producer] Emit of '{action}' to '{stream_name}' failed "
                    f"({type(e).__name__}), attempt {attempt}/{attempts}. Retrying."
                )
                await asyncio.sleep(retry_delay * 2 ** (attempt - 1))

        if pipe is None:
            logger.info(
                f"[Producer] Emitted '{action}' to '{stream_name}' (ID: {message_id})"
            )

        return message_id

    async def emit_safe(
        self,
        stream_name: str,
        action: str,
        payload: dict[str, Any],
        *,
        maxlen: int | None = None,
        retries: int = 2,
        retry_delay: float = 0.2,
    ) -> str | None:
        """
        Like `emit`, with retries, and it never raises: a failure is logged and the
        result is None. For background tasks after a commit, where nobody is left
        to handle the error and the request has already been answered.
        """
        try:
            return await self.emit(
                stream_name,
                action,
                payload,
                maxlen=maxlen,
                retries=retries,
                retry_delay=retry_delay,
            )
        except Exception:
            return None  # emit has logged the reason
