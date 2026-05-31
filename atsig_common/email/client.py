from dataclasses import dataclass
from typing import Literal, Optional
from celery import Celery
from ..logger.config import get_logger

logger = get_logger("atsig_common.email.client")


# 1. Gather all "Magic Constants" into a single object
@dataclass(frozen=True)
class EmailServiceConfig:
    # These must MATCH EXACTLY with the Email Service (Worker) settings
    TASK_SEND_HIGH: str = "email.send_high"
    TASK_SEND_LOW: str = "email.send_low"
    TASK_SEND_BULK: str = "email.send_bulk"

    QUEUE_HIGH: str = "high_priority"
    QUEUE_LOW: str = "low_priority"


class AsyncEmailClient:
    """
    Lightweight client for sending tasks to the Email Service Celery worker.
    """

    def __init__(self, broker_url: str):
        # Create the "communication channel" with the Redis broker
        self.celery_app = Celery("email_client", broker=broker_url)

        # Store the configuration for easy access
        self.config = EmailServiceConfig()

    def send_email(
        self,
        template_name: str,
        context: dict,
        user_id: Optional[str] = None,
        recipient_email: Optional[str] = None,
        priority: Literal["high", "low"] = "high",
    ) -> str:
        """
        Puts the email into the appropriate queue (high or low priority).
        Returns the Celery Task ID.
        """
        if not user_id and not recipient_email:
            raise ValueError(
                "At least one must be provided: user_id or recipient_email."
            )

        # Select the correct Task AND Queue based on priority
        if priority == "high":
            task_name = self.config.TASK_SEND_HIGH
            queue = self.config.QUEUE_HIGH
        else:
            task_name = self.config.TASK_SEND_LOW
            queue = self.config.QUEUE_LOW

        try:
            # Send the Task
            task = self.celery_app.send_task(
                name=task_name,
                kwargs={
                    "template_name": template_name,
                    "context": context,
                    "user_id": str(user_id) if user_id else None,
                    "recipient_email": recipient_email,
                },
                queue=queue,
            )

            logger.info(
                f"[EmailClient] Queued email '{template_name}' "
                f"(Task ID: {task.id}) in queue '{queue}'"
            )
            return task.id

        except Exception as e:
            logger.error(f"[EmailClient] Failed to send task to Celery: {e}")
            raise e

    def send_bulk_emails(
        self,
        template_name: str,
        context: dict,
        user_ids: Optional[list[str]] = None,
        recipients: Optional[list[str]] = None,
    ) -> str:
        """
        Sends a single task to Celery containing multiple recipients.
        The worker will split this into individual low-priority emails using a group.
        """
        if not user_ids and not recipients:
            raise ValueError("Must provide at least one list: user_ids or recipients.")

        payload = {
            "template_name": template_name,
            "context": context,
            "user_ids": user_ids or [],
            "recipients": recipients or [],
        }

        try:
            # 🔹 Τα bulk tasks πηγαίνουν ΠΑΝΤΑ στη low_priority queue
            # για να μην μπλοκάρουν ποτέ τα password resets / registrations
            task = self.celery_app.send_task(
                name=self.config.TASK_SEND_BULK,
                kwargs=payload,
                queue=self.config.QUEUE_LOW,
            )

            logger.info(
                f"[EmailClient] Queued BULK task '{template_name}' "
                f"(Task ID: {task.id}) for {len(payload['user_ids']) + len(payload['recipients'])} recipients."
            )
            return task.id

        except Exception as e:
            logger.error(f"[EmailClient] Failed to queue bulk email task: {e}")
            raise e
