import asyncio
import enum
import json
import socket
import time
import uuid
from typing import Any

from redis.exceptions import ResponseError

from ..events.schemas import dlq_name
from ..exceptions import NonRetryableError
from ..logger.config import get_logger
from ..logger.context import is_valid_request_id, request_id_var
from .manager import RedisManager

logger = get_logger("atsig_common.redis.consumer")


class ConsumerOutcome(enum.StrEnum):
    """
    What a consumer did with an event: changed the data, or left it alone (a stale or
    duplicate event). `process_message` may return it; the base consumer ACKs the
    message either way and only logs the outcome. The DLQ replay of a service can
    show it to the admin.
    """

    applied = "applied"
    ignored = "ignored"


def consumer_name_from_hostname(prefix: str) -> str:
    """
    A consumer name that is the same on every start of the same container
    (`prefix_<hostname>`). Pass it as `consumer_name`, so that a restart does not
    leave a new dead name in the group each time. The hostname of a container changes
    only when the container is created again.
    """
    return f"{prefix}_{socket.gethostname()}"


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
    - Reclaim of the messages that a dead consumer left pending (XAUTOCLAIM), with a
      limit of deliveries, after which a message goes to the DLQ
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
        max_loop_failures: int = 20,
        loop_error_delay: float = 5,
        loop_error_max_delay: float = 60,
        consumer_name: str | None = None,
        reclaim_idle_ms: int = 120_000,
        reclaim_interval_s: float = 60,
        max_deliveries: int = 5,
    ):
        self.redis_manager = redis_manager
        self.stream_name = stream_name
        self.group_name = group_name

        # A random name per start by default, so two copies of a worker never share
        # one. Give a fixed name (see `consumer_name_from_hostname`) to keep the same
        # consumer across restarts instead of leaving a new dead name in the group
        # each time.
        self.consumer_name = (
            consumer_name or f"{consumer_prefix}_{uuid.uuid4().hex[:6]}"
        )
        self.dlq_name = dlq_name(stream_name)

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

        # When reading from Redis keeps failing (it is down, the connection broke),
        # `run` waits `loop_error_delay` seconds, then twice as long, up to
        # `loop_error_max_delay`. After `max_loop_failures` failures IN A ROW it gives
        # up and raises, so the process exits and the orchestrator restarts it. A
        # consumer that retried silently for ever looked alive and did nothing.
        # 0 means never give up.
        self.max_loop_failures = max_loop_failures
        self.loop_error_delay = loop_error_delay
        self.loop_error_max_delay = loop_error_max_delay

        # A message that was delivered and never ACKed (the consumer died while
        # handling it, or the DLQ could not be written) stays PENDING. Every
        # `reclaim_interval_s` seconds, and at start, this consumer takes over the
        # pending messages that have been idle for `reclaim_idle_ms`. That must be
        # longer than the longest time one message can take to handle, or a slow
        # message would be handled twice at once (handlers are idempotent anyway).
        # A message that was already delivered `max_deliveries` times goes to the DLQ
        # instead of being handled again: this stops a message that kills the process
        # from looping for ever.
        self.reclaim_idle_ms = reclaim_idle_ms
        self.reclaim_interval_s = reclaim_interval_s
        self.max_deliveries = max_deliveries

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

        Raises:
            Exception: when the entry could not be written. The caller must then NOT
                ACK the message: it stays pending, and is handled again after
                `reclaim_idle_ms`. (It used to be ACKed here, which lost it.)
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
                f"It stays pending and will be retried. "
                f"Error: {type(dlq_err).__name__}"
            )
            raise

    async def process_message(
        self,
        message_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> ConsumerOutcome | None:
        """
        Override this method in each service. Return `ConsumerOutcome.applied` or
        `ConsumerOutcome.ignored` if you want it logged; `None` is fine too.
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

    def _request_id_of(self, raw_payload: dict[str, Any]) -> str | None:
        """The request id the producer put in `meta`. A bad or missing `meta` is ignored."""
        try:
            meta = {self._decode(k): self._decode(v) for k, v in raw_payload.items()}
            request_id = json.loads(meta.get("meta") or "{}")["request_id"]
        except Exception:
            return None
        return request_id if is_valid_request_id(request_id) else None

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

    async def _delivery_count(self, message_id: str) -> int | None:
        """How many times Redis has delivered the message (None when it can not tell)."""
        try:
            rows = await self.redis_manager.xpending_range(
                self.stream_name,
                self.group_name,
                min=message_id,
                max=message_id,
                count=1,
            )
            return int(rows[0]["times_delivered"]) if rows else None
        except Exception:
            return None

    async def _dead_letter_reclaimed(
        self, message_id: str, fields: dict[str, Any], deliveries: int
    ):
        """A message that was delivered too many times: to the DLQ, then ACK."""
        logger.error(
            f"[Consumer] Message {message_id} was delivered {deliveries} times "
            f"(limit {self.max_deliveries}). Sending to DLQ."
        )
        await self._send_to_dlq(
            message_id=message_id,
            raw_payload={str(k): v for k, v in fields.items()},
            error_msg=f"Delivery limit reached ({deliveries} deliveries)",
        )
        await self.redis_manager.xack(self.stream_name, self.group_name, message_id)

    async def _handle_reclaimed(self, claimed: list[tuple[str, dict[str, Any] | None]]):
        tasks = []
        for message_id, fields in claimed:
            if fields is None:
                # The entry was trimmed from the stream (MAXLEN) while it was pending:
                # there is nothing left to handle.
                await self.redis_manager.xack(
                    self.stream_name, self.group_name, message_id
                )
                continue

            deliveries = await self._delivery_count(message_id)
            if deliveries is not None and deliveries > self.max_deliveries:
                tasks.append(
                    self._dead_letter_reclaimed(message_id, fields, deliveries)
                )
            else:
                tasks.append(self._handle_message(message_id, fields))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _reclaim_pending(self) -> int:
        """
        Takes over the messages that were delivered, never ACKed, and have been idle
        for `reclaim_idle_ms` (a consumer died, or the DLQ was down), and handles them.
        Returns how many it took.
        """
        reclaimed = 0
        start_id = "0-0"

        while self._is_running:
            result = await self.redis_manager.xautoclaim(
                self.stream_name,
                self.group_name,
                self.consumer_name,
                min_idle_time=self.reclaim_idle_ms,
                start_id=start_id,
                count=self.batch_size,
            )
            next_id, claimed = result[0], result[1]

            if claimed:
                reclaimed += len(claimed)
                logger.warning(
                    f"[Consumer] Reclaimed {len(claimed)} pending message(s) of "
                    f"'{self.stream_name}'."
                )
                await self._handle_reclaimed(claimed)

            # "0-0" is the end of the scan; also stop if the cursor does not move
            if next_id in ("0-0", b"0-0") or next_id == start_id:
                break
            start_id = next_id

        return reclaimed

    async def _handle_message(
        self,
        message_id: str,
        raw_payload: dict[str, Any],
    ):
        """
        Handle a single message lifecycle, logging under the id of the request that
        caused the event (or under the id of the entry, when it carries none).
        """
        token = request_id_var.set(self._request_id_of(raw_payload) or message_id)
        try:
            await self._handle_entry(message_id, raw_payload)
        finally:
            request_id_var.reset(token)

    async def _handle_entry(
        self,
        message_id: str,
        raw_payload: dict[str, Any],
    ):
        # The semaphore limits the messages being PROCESSED at the same time. It is
        # taken for an attempt only, never while waiting before the next attempt: a
        # failing message must not hold a slot while it sleeps.
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

                    async with self._semaphore:
                        outcome = await self.process_message(
                            message_id, action, payload
                        )

                        await self.redis_manager.xack(
                            self.stream_name,
                            self.group_name,
                            message_id,
                        )

                    logger.debug(
                        f"[Consumer] Message {message_id} ACKed successfully"
                        f"{f' ({outcome})' if outcome else ''}."
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
            # Something went wrong around the handling itself (Redis, the DLQ). The
            # message is NOT ACKed: it stays pending and is reclaimed, and after
            # `max_deliveries` deliveries it goes to the DLQ.
            logger.error(
                f"[Consumer] Handler error for {message_id}, the message stays "
                f"pending: {type(fatal_error).__name__}"
            )

    async def run(self):

        await self._ensure_consumer_group()

        self._is_running = True

        logger.info(
            f"[Consumer] Starting "
            f"{self.consumer_name} "
            f"listening to {self.stream_name}..."
        )

        failures = 0  # reads that failed IN A ROW
        last_reclaim: float | None = None  # monotonic time of the last reclaim

        while self._is_running:
            try:
                # First thing at start, and then every `reclaim_interval_s`
                now = time.monotonic()
                if (
                    last_reclaim is None
                    or now - last_reclaim >= self.reclaim_interval_s
                ):
                    await self._reclaim_pending()
                    last_reclaim = time.monotonic()

                response = await self.redis_manager.xreadgroup(
                    groupname=self.group_name,
                    consumername=self.consumer_name,
                    streams={self.stream_name: ">"},
                    count=self.batch_size,
                    block=self.block_ms,
                )
                failures = 0

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
                # The task ends as cancelled, so whoever cancelled it can tell
                # (swallowing the cancellation made it look like a normal end).
                raise

            except Exception as loop_error:
                failures += 1
                give_up = bool(self.max_loop_failures) and (
                    failures >= self.max_loop_failures
                )
                delay = min(
                    self.loop_error_delay * 2 ** (failures - 1),
                    self.loop_error_max_delay,
                )
                # Only the type: the text of an error can hold values.
                logger.error(
                    f"[Consumer] Loop error {type(loop_error).__name__} "
                    f"({failures} in a row"
                    + (", giving up" if give_up else f", retrying in {delay:g}s")
                    + ")"
                )

                if give_up:
                    self._is_running = False
                    raise

                await asyncio.sleep(delay)

    def stop(self):
        """
        Gracefully stop consumer loop.
        """
        self._is_running = False
