from dataclasses import dataclass
from celery import Celery
from ..logger.config import get_logger

logger = get_logger("atsig_common.email.client")


# 1. Gather all "Magic Constants" into a single object
@dataclass(frozen=True)
class EmailServiceConfig:
    # These must MATCH EXACTLY with the Email Service (Worker) settings
    TASK_SEND_TEMPLATE: str = "email.send_single_template"
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
        user_id: str = None,
        recipient_email: str = None,
        priority: str = "high",
    ) -> str:
        """
        Puts the email into the appropriate queue (high or low priority).
        Returns the Celery Task ID.
        """
        if not user_id and not recipient_email:
            raise ValueError(
                "At least one must be provided: user_id or recipient_email."
            )

        # Select the correct queue based on priority
        queue = self.config.QUEUE_HIGH if priority == "high" else self.config.QUEUE_LOW

        try:
            # Send the Task
            task = self.celery_app.send_task(
                name=self.config.TASK_SEND_TEMPLATE,
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
