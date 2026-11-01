import json
import logging
from typing import Any

from atsig_common.logger.context import request_id_var, user_email_var, user_id_var


class UnifiedFormatter(logging.Formatter):
    """
    Custom logging formatter that outputs logs as structured JSON strings.
    Optimized for modern log aggregators like Grafana Loki or ELK.

    Args:
        include_user_email: Writes the email of the user on every line. Turn it off
            to keep personal data out of the logs (the user id stays).
    """

    def __init__(
        self, *args: Any, include_user_email: bool = True, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.include_user_email = include_user_email

    def format(self, record: logging.LogRecord) -> str:
        # 1. Fetch metadata from ContextVars
        req_id = request_id_var.get()
        usr_id = user_id_var.get() or "anonymous"
        usr_email = user_email_var.get() or "no-email"

        # 2. Build the structured log dictionary
        log_record = {
            "timestamp": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "request_id": req_id,
            "user_id": usr_id,
            "user_email": usr_email,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if not self.include_user_email:
            del log_record["user_email"]

        # 3. If there is an exception stack trace, inject it into the JSON
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        # 4. Convert to a compact JSON string (ensure_ascii=False preserves Greek characters)
        return json.dumps(log_record, ensure_ascii=False)


def get_logging_config(
    service_name: str, level: str = "INFO", include_user_email: bool = True
) -> dict[str, Any]:
    """
    Generates the comprehensive logging configuration dictionary.
    Safe for Uvicorn/FastAPI applications.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "()": "atsig_common.logger.config.UnifiedFormatter",
                "include_user_email": include_user_email,
            }
        },
        "handlers": {
            "default": {
                "formatter": "standard",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            }
        },
        "loggers": {
            "": {"handlers": ["default"], "level": level},
            "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.error": {
                "level": level,
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": [],
                "level": "WARNING",
                "propagate": False,
            },
            service_name: {"handlers": ["default"], "level": level, "propagate": False},
        },
    }


def get_logger(name: str) -> logging.Logger:
    """
    Utility function to retrieve a standard logger instance.

    Args:
        name (str): The name of the logger, typically __name__.

    Returns:
        logging.Logger: The requested logger instance.
    """
    return logging.getLogger(name)
