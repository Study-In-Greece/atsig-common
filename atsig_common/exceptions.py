class AtsigError(Exception):
    def __init__(self, message: str = "An error occurred"):
        self.message = message
        super().__init__(self.message)


class NotFoundError(AtsigError):
    pass


class ForbiddenError(AtsigError):
    pass


class UnauthorizedError(AtsigError):
    pass


class BadRequestError(AtsigError):
    pass


class ConflictError(AtsigError):
    pass


class UpstreamError(AtsigError):
    """
    A service that this one calls failed, refused the call (its 401/403 for the token
    of this service) or could not be reached. It is the fault of neither the user nor
    this service, so it is answered as 502 (504 for a timeout), with a message that
    holds no internal detail: the detail goes to the log only.
    """

    def __init__(
        self,
        message: str = "A service this one depends on did not answer correctly. "
        "Please try again later.",
        status_code: int = 502,
    ):
        super().__init__(message)
        self.status_code = status_code


class ServiceUnavailableError(AtsigError):
    """
    A service this one depends on can not be reached right now (503). The message
    goes to the client, so it must not hold internal details.
    """


class NonRetryableError(Exception):
    """
    Raise this when a failure is deterministic - retrying won't help
    (e.g. invalid payload schema). Skips remaining retry attempts and
    goes straight to DLQ instead of wasting retry_delay cycles.

    The message is logged and stored in the DLQ as it is: name fields and error
    types only, never their values (names, emails). Any other exception is
    recorded by its type name alone.
    """
