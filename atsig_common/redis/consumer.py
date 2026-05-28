import asyncio
import json
import uuid
from typing import Dict, Any

from redis.exceptions import ResponseError

from .manager import RedisManager
from ..logger.config import get_logger

logger = get_logger("atsig_common.redis.consumer")


class BaseRedisConsumer:
    """
    Base Redis Stream Consumer with:
    - Consumer Groups
    - Concurrent Processing
    - Retry Strategy
    - Dead Letter Queue
    - Graceful Shutdown
    - Emergency ACK Policy
    """

    def __init__(
        self,
        redis_manager: RedisManager,
        stream_name: str,
        group_name: str,
        consumer_prefix: str = "worker",
        block_ms: int = 5000,
        batch_size: int = 10,
        max_retries: int = 3,
        retry_delay: int = 2,
        concurrency: int = 10,
    ):
        self.redis_manager = redis_manager
        self.stream_name = stream_name
        self.group_name = group_name

        self.consumer_name = f"{consumer_prefix}_{uuid.uuid4().hex[:6]}"
        self.dlq_name = f"{stream_name}_dlq"

        self.block_ms = block_ms
        self.batch_size = batch_size

        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._is_running = False
        self._semaphore = asyncio.Semaphore(concurrency)

    async def _ensure_consumer_group(self):
        """
        Create consumer group if it does not exist.
        '$' means consume only new messages.
        """
        try:
            await self.redis_manager.xgroup_create(
                name=self.stream_name,
                groupname=self.group_name,
                id="$",
                mkstream=True,
            )

            logger.info(
                f"[Consumer] Group '{self.group_name}' created on '{self.stream_name}'."
            )

        except ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug(f"[Consumer] Group '{self.group_name}' already exists.")
            else:
                raise e

    async def _send_to_dlq(
        self,
        message_id: str,
        raw_payload: Any,
        error_msg: str,
    ):
        """
        Send failed message to Dead Letter Queue.
        """

        try:
            await self.redis_manager.xadd(
                name=self.dlq_name,
                fields={
                    "original_message_id": message_id,
                    "payload": json.dumps(raw_payload, default=str),
                    "error": error_msg,
                    "consumer_group": self.group_name,
                },
            )

            logger.warning(
                f"[Consumer] Message {message_id} moved to DLQ ({self.dlq_name})."
            )

        except Exception as dlq_err:
            logger.critical(
                f"[Consumer] FAILED TO WRITE TO DLQ for message {message_id}. "
                f"Emergency ACK will be applied. Error: {dlq_err}"
            )

            # Emergency ACK policy to prevent poison message loops
            try:
                await self.redis_manager.xack(
                    self.stream_name,
                    self.group_name,
                    message_id,
                )

                logger.critical(f"[Consumer] Emergency ACK applied for {message_id}.")

            except Exception as ack_err:
                logger.critical(
                    f"[Consumer] Emergency ACK FAILED for {message_id}. "
                    f"Manual intervention required. Error: {ack_err}"
                )

    async def process_message(
        self,
        message_id: str,
        action: str,
        payload: Dict[str, Any],
    ):
        """
        Override this method in each service.
        """
        raise NotImplementedError("Subclasses must implement process_message()")

    def _decode(self, value):
        """
        Normalize Redis bytes/strings.
        """

        if isinstance(value, bytes):
            return value.decode("utf-8")

        return value

    async def _handle_message(
        self,
        message_id: str,
        raw_payload: Dict[str, Any],
    ):
        """
        Handle a single message lifecycle.
        """

        async with self._semaphore:

            try:
                normalized_payload = {
                    self._decode(k): self._decode(v) for k, v in raw_payload.items()
                }

                action = normalized_payload.get("action")
                raw_data = normalized_payload.get("data")

                if action is None or raw_data is None:
                    raise ValueError(
                        "Invalid message format: missing 'action' or 'data'"
                    )

                payload = json.loads(raw_data)

                last_error = None

                for attempt in range(1, self.max_retries + 1):

                    try:
                        logger.debug(
                            f"[Consumer] Processing message "
                            f"{message_id} (attempt {attempt})"
                        )

                        await self.process_message(
                            message_id,
                            action,
                            payload,
                        )

                        # ACK only after successful processing
                        await self.redis_manager.xack(
                            self.stream_name,
                            self.group_name,
                            message_id,
                        )

                        logger.debug(
                            f"[Consumer] Message {message_id} ACKed successfully."
                        )

                        return

                    except Exception as processing_error:

                        last_error = str(processing_error)

                        logger.error(
                            f"[Consumer] Error processing "
                            f"{message_id} "
                            f"(attempt {attempt}/{self.max_retries}): "
                            f"{last_error}"
                        )

                        if attempt < self.max_retries:
                            await asyncio.sleep(self.retry_delay)

                # Max retries exceeded -> DLQ
                logger.error(
                    f"[Consumer] Max retries exceeded for "
                    f"{message_id}. Sending to DLQ."
                )

                await self._send_to_dlq(
                    message_id=message_id,
                    raw_payload=normalized_payload,
                    error_msg=last_error,
                )

                # ACK after DLQ
                await self.redis_manager.xack(
                    self.stream_name,
                    self.group_name,
                    message_id,
                )

            except Exception as fatal_error:

                logger.exception(
                    f"[Consumer] Fatal handler error for "
                    f"{message_id}: {fatal_error}"
                )

                # Emergency ACK to prevent infinite poison loops
                try:
                    await self.redis_manager.xack(
                        self.stream_name,
                        self.group_name,
                        message_id,
                    )

                    logger.critical(
                        f"[Consumer] Emergency ACK applied for " f"{message_id}."
                    )

                except Exception as ack_error:
                    logger.critical(
                        f"[Consumer] Emergency ACK FAILED for "
                        f"{message_id}: {ack_error}"
                    )

    async def run(self):

        await self._ensure_consumer_group()

        self._is_running = True

        logger.info(
            f"[Consumer] Starting "
            f"{self.consumer_name} "
            f"listening to {self.stream_name}..."
        )

        while self._is_running:

            try:
                response = await self.redis_manager.xreadgroup(
                    groupname=self.group_name,
                    consumername=self.consumer_name,
                    streams={self.stream_name: ">"},
                    count=self.batch_size,
                    block=self.block_ms,
                )

                if not response:
                    continue

                tasks = []

                for _, messages in response:

                    for message_id, raw_payload in messages:

                        tasks.append(
                            self._handle_message(
                                message_id,
                                raw_payload,
                            )
                        )

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            except asyncio.CancelledError:

                logger.info(f"[Consumer] {self.consumer_name} stopping gracefully...")

                self._is_running = False
                break

            except Exception as loop_error:

                logger.exception(
                    f"[Consumer] Critical loop error: "
                    f"{loop_error}. Retrying in 5s..."
                )

                await asyncio.sleep(5)

    def stop(self):
        """
        Gracefully stop consumer loop.
        """
        self._is_running = False
