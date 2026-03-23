import logging
from typing import Any, Dict


class ColorFormatter(logging.Formatter):
    """Custom Formatter που προσθέτει χρώματα στο τερματικό"""

    # ANSI Colors
    GREY = "\x1b[38;20m"
    BLUE = "\x1b[34;20m"
    CYAN = "\x1b[36;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    # Το format που ζήτησες: Ημερομηνία - Level - Name - Message
    # Το -8s ευθυγραμμίζει το Level (π.χ. INFO    vs WARNING )
    base_fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    FORMATS = {
        logging.DEBUG: GREY + base_fmt + RESET,
        logging.INFO: CYAN + base_fmt + RESET,
        logging.WARNING: YELLOW + base_fmt + RESET,
        logging.ERROR: RED + base_fmt + RESET,
        logging.CRITICAL: BOLD_RED + base_fmt + RESET,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno, self.base_fmt)
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


def get_logger(name: str):
    return logging.getLogger(name)


def get_logging_config(service_name: str, level: str = "INFO") -> Dict[str, Any]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "pretty": {
                # Εδώ λέμε στο logging να χρησιμοποιήσει την κλάση μας!
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
