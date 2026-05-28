import json
from typing import Any, Dict, Optional, Union

from redis.client import Pipeline

from .manager import RedisManager
from ..logger.config import get_logger

logger = get_logger("atsig_common.redis.producer")


class EventProducer:
    """
    A class for standardized event emitting to Redis Streams.
    """

    def __init__(self, redis_manager: RedisManager):
        self.redis_manager = redis_manager

    async def emit(
        self,
        stream_name: str,
        action: str,
        payload: Dict[str, Any],
        pipe: Optional[Union[RedisManager, Pipeline]] = None,
    ) -> str:
        """
        Publishes an event to the specified Redis Stream.

        Embeds the action into the payload and serializes it to JSON
        under the "data" key (exactly as our BaseConsumer expects).
        """
        try:
            stream_data = {"action": action, "data": json.dumps(payload, default=str)}

            target = pipe if pipe is not None else self.redis_manager

            message_id = await target.xadd(stream_name, stream_data)

            if not pipe:
                logger.info(
                    f"[Producer] Emitted '{action}' to '{stream_name}' (ID: {message_id})"
                )

            return message_id

        except Exception as e:
            logger.error(
                f"[Producer] Failed to emit '{action}' to '{stream_name}': {e}"
            )
            raise e
