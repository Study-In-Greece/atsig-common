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
        priority: Literal["high", "low"] = "high",  # 🔹 ΤΕΛΕΙΟ TYPE SAFETY
    ) -> str:
        """
        Puts the email into the appropriate queue (high or low priority).
        Returns the Celery Task ID.
        """
        if not user_id and not recipient_email:
            raise ValueError(
                "At least one must be provided: user_id or recipient_email."
            )

        # 🔹 Select the correct Task AND Queue based on priority
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
