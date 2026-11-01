import contextvars
import re

# The id of a request, as a client, a proxy or another service may send it: short and
# made of safe characters only. Anything else is replaced by a generated id, so a
# client can not put arbitrary text in our logs, our Sentry events and headers.
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")

# What the request id holds outside of a request (and what the logs then show)
NO_REQUEST_ID = "-"


def is_valid_request_id(value: object) -> bool:
    """A real id: made of safe characters, and not the placeholder of 'no request'."""
    return (
        isinstance(value, str)
        and value != NO_REQUEST_ID
        and REQUEST_ID_PATTERN.fullmatch(value) is not None
    )


# Context variables to store request-specific metadata across async tasks
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=NO_REQUEST_ID
)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "user_id", default=None
)
user_email_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "user_email", default=None
)


def current_request_id() -> str | None:
    """The id of the request being served, or None outside of a request."""
    value = request_id_var.get()
    return value if is_valid_request_id(value) else None
