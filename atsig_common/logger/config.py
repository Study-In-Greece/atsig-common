import logging
from typing import Any, Dict


class ColorFormatter(logging.Formatter):
    """
    Custom logging formatter that adds ANSI color codes to terminal output.

    This formatter maps different logging levels to specific colors to improve
    readability in development environments.
    """

    # ANSI Color Escape Codes
    GREY = "\x1b[38;20m"
    BLUE = "\x1b[34;20m"
    CYAN = "\x1b[36;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    # Base format string shared across all levels
    base_fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    # Mapping of logging levels to colored format strings
    FORMATS = {
        logging.DEBUG: GREY + base_fmt + RESET,
        logging.INFO: CYAN + base_fmt + RESET,
        logging.WARNING: YELLOW + base_fmt + RESET,
        logging.ERROR: RED + base_fmt + RESET,
        logging.CRITICAL: BOLD_RED + base_fmt + RESET,
    }

    def format(self, record):
        """
        Formats the log record with the appropriate color based on its level.

        Args:
            record (logging.LogRecord): The log record to be formatted.

        Returns:
            str: The formatted and colorized log string.
        """
        log_fmt = self.FORMATS.get(record.levelno, self.base_fmt)
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


def get_logger(name: str):
    """
    Utility function to retrieve a standard logger instance.

    Args:
        name (str): The name of the logger, typically __name__.

    Returns:
        logging.Logger: The requested logger instance.
    """
    return logging.getLogger(name)


def get_logging_config(service_name: str, level: str = "INFO") -> Dict[str, Any]:
    """
    Generates a comprehensive logging configuration dictionary.

    This configuration is compatible with logging.config.dictConfig and is
    specifically tailored for FastAPI/Uvicorn applications. It includes
    separate handlers for general logs (pretty-printed) and access logs.

    Args:
        service_name (str): The name of the specific service logger to configure.
        level (str): The global logging level (e.g., "DEBUG", "INFO"). Defaults to "INFO".

    Returns:
        Dict[str, Any]: A dictionary containing the full logging setup.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "pretty": {
                "()": "atsig_common.logger.config.ColorFormatter",
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(asctime)s | %(levelname)-8s | %(name)s | %(client_addr)s - "%(request_line)s" %(status_code)s',
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "default": {
                "formatter": "pretty",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
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
