import contextvars
from typing import Optional

# Context variables to store request-specific metadata across async tasks
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
user_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "user_id", default=None
)
user_email_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "user_email", default=None
)
