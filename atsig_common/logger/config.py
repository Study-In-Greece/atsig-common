import logging
import os
from typing import Any, Dict
from atsig_common.logger.context import request_id_var, user_id_var, user_email_var


class UnifiedFormatter(logging.Formatter):
    """
    Custom logging formatter that dynamically injects Request ID, User ID, and User Email.
    Automatically disables ANSI colors if running in a production environment.
    """

    # ANSI Color Codes
    CYAN = "\x1b[36;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    FORMATS = {
        logging.DEBUG: RESET,
        logging.INFO: CYAN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def __init__(self, fmt: str = None, datefmt: str = None):
        super().__init__(fmt, datefmt)
        # Disable colors if ENVIRONMENT env var is set to 'production'
        self.use_colors = (
            os.getenv("ENVIRONMENT", "development").lower() != "production"
        )

    def format(self, record: logging.LogRecord) -> str:
        # 1. Fetch metadata from ContextVars
        req_id = request_id_var.get()
        usr_id = user_id_var.get() or "anonymous"
        usr_email = user_email_var.get() or "no-email"

        # 2. Attach them to the record so they can be formatted
        record.request_id = req_id
        record.user_id = usr_id
        record.user_email = usr_email

        # 3. Apply color if applicable
        if self.use_colors:
            color = self.FORMATS.get(record.levelno, self.RESET)
            log_fmt = f"{color}%(asctime)s | %(levelname)-8s | req:%(request_id)s | email:%(user_email)s | %(name)s | %(message)s{self.RESET}"
        else:
            log_fmt = "%(asctime)s | %(levelname)-8s | req:%(request_id)s | email:%(user_email)s | %(name)s | %(message)s"

        # Override formatter configuration dynamically
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


def get_logging_config(service_name: str, level: str = "INFO") -> Dict[str, Any]:
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
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(asctime)s | %(levelname)-8s | %(client_addr)s - "%(request_line)s" %(status_code)s',
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "default": {
                "formatter": "standard",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",  # Send all app logs to stdout for Docker
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
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
                "handlers": ["access"],
                "level": level,
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
