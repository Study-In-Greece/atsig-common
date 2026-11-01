import asyncio
import json
import uuid
from typing import Any

from redis.exceptions import ResponseError

from ..exceptions import NonRetryableError
from ..logger.config import get_logger
from .manager import RedisManager

logger = get_logger("atsig_common.redis.consumer")


class InvalidMessageError(ValueError):
    """
    A stream entry is not a valid message envelope. Retrying cannot help, so the
    entry goes straight to the DLQ. The text never holds values of the message.
    """


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
        group_start_id: str = "0",
        dlq_maxlen: int | None = None,
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

        # Where a NEW consumer group starts reading. "0" is the beginning of the
        # stream, so events sent before the group existed (a new environment, a new
        # stream) are not lost. "$" would read only what arrives afterwards.
        # An existing group keeps its own position and ignores this.
        self.group_start_id = group_start_id

        # When set, the DLQ is trimmed to about this many entries (oldest first).
        # None keeps every failed entry until somebody discards it.
        self.dlq_maxlen = dlq_maxlen

        self._is_running = False
        self._semaphore = asyncio.Semaphore(concurrency)

    async def _ensure_consumer_group(self):
        """
        Create consumer group if it does not exist, starting at `group_start_id`.
        """
        try:
            await self.redis_manager.xgroup_create(
                name=self.stream_name,
                groupname=self.group_name,
                id=self.group_start_id,
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

    def _dlq_options(self) -> dict[str, Any]:
        if self.dlq_maxlen is None:
            return {}
        return {"maxlen": self.dlq_maxlen, "approximate": True}

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
                **self._dlq_options(),
            )

            logger.warning(
                f"[Consumer] Message {message_id} moved to DLQ ({self.dlq_name})."
            )

        except Exception as dlq_err:
            logger.critical(
                f"[Consumer] FAILED TO WRITE TO DLQ for message {message_id}. "
                f"Emergency ACK will be applied. Error: {type(dlq_err).__name__}"
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
                    f"Manual intervention required. Error: {type(ack_err).__name__}"
                )

    async def process_message(
        self,
        message_id: str,
        action: str,
        payload: dict[str, Any],
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

    @staticmethod
    def _parse_envelope(normalized_payload: dict[str, Any]) -> tuple[str, dict]:
        """
        Splits a stream entry into (action, payload).

        Raises:
            InvalidMessageError: the entry has no action or data, or the data is
                not a JSON object.
        """
        action = normalized_payload.get("action")
        raw_data = normalized_payload.get("data")

        if action is None or raw_data is None:
            raise InvalidMessageError("missing 'action' or 'data'")

        try:
            payload = json.loads(raw_data)
        except (TypeError, ValueError):
            raise InvalidMessageError("'data' is not valid JSON") from None

        if not isinstance(payload, dict):
            raise InvalidMessageError("'data' is not a JSON object")

        return action, payload

    async def _reject_invalid_message(
        self, message_id: str, raw_payload: dict[str, Any], reason: str
    ):
        """Sends an entry that is not a valid message to the DLQ, then ACKs it."""
        logger.error(
            f"[Consumer] Invalid message {message_id}: {reason}. Sending to DLQ."
        )

        await self._send_to_dlq(
            message_id=message_id,
            raw_payload={str(key): value for key, value in raw_payload.items()},
            error_msg=f"Invalid message: {reason}",
        )

        await self.redis_manager.xack(
            self.stream_name,
            self.group_name,
            message_id,
        )

    async def _handle_message(
        self,
        message_id: str,
        raw_payload: dict[str, Any],
    ):
        """
        Handle a single message lifecycle.
        """

        async with self._semaphore:
            try:
                try:
                    normalized_payload = {
                        self._decode(k): self._decode(v) for k, v in raw_payload.items()
                    }
                    action, payload = self._parse_envelope(normalized_payload)
                except Exception as envelope_error:
                    reason = (
                        str(envelope_error)
                        if isinstance(envelope_error, InvalidMessageError)
                        else f"unreadable entry ({type(envelope_error).__name__})"
                    )
                    await self._reject_invalid_message(message_id, raw_payload, reason)
                    return

                last_error = None

                skipped_retries = False

                for attempt in range(1, self.max_retries + 1):
                    try:
                        logger.debug(
                            f"[Consumer] Processing message "
                            f"{message_id} (attempt {attempt})"
                        )

                        await self.process_message(message_id, action, payload)

                        await self.redis_manager.xack(
                            self.stream_name,
                            self.group_name,
                            message_id,
                        )

                        logger.debug(
                            f"[Consumer] Message {message_id} ACKed successfully."
                        )
                        return

                    except NonRetryableError as non_retryable_error:
                        last_error = str(non_retryable_error)
                        skipped_retries = True

                        logger.error(
                            f"[Consumer] Non-retryable error processing {message_id}: "
                            f"{last_error}. Skipping remaining retries."
                        )
                        break

                    except Exception as processing_error:
                        last_error = type(processing_error).__name__

                        logger.error(
                            f"[Consumer] Error processing {message_id} "
                            f"(attempt {attempt}/{self.max_retries}): {last_error}"
                        )

                        if attempt < self.max_retries:
                            await asyncio.sleep(self.retry_delay)

                # Max retries exceeded OR non-retryable error -> DLQ
                logger.error(
                    f"[Consumer] {'Non-retryable error' if skipped_retries else 'Max retries exceeded'} "
                    f"for {message_id}. Sending to DLQ."
                )

                await self._send_to_dlq(
                    message_id=message_id,
                    raw_payload=normalized_payload,
                    error_msg=last_error,
                )

                await self.redis_manager.xack(
                    self.stream_name,
                    self.group_name,
                    message_id,
                )

            except Exception as fatal_error:
                logger.error(
                    f"[Consumer] Fatal handler error for {message_id}: "
                    f"{type(fatal_error).__name__}"
                )

                # Emergency ACK to prevent infinite poison loops
                try:
                    await self.redis_manager.xack(
                        self.stream_name,
                        self.group_name,
                        message_id,
                    )

                    logger.critical(
                        f"[Consumer] Emergency ACK applied for {message_id}."
                    )

                except Exception as ack_error:
                    logger.critical(
                        f"[Consumer] Emergency ACK FAILED for {message_id}: {type(ack_error).__name__}"
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
                    f"[Consumer] Critical loop error: {loop_error}. Retrying in 5s..."
                )

                await asyncio.sleep(5)

    def stop(self):
        """
        Gracefully stop consumer loop.
        """
        self._is_running = False
