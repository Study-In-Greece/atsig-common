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


class NonRetryableError(Exception):
    """
    Raise this when a failure is deterministic - retrying won't help
    (e.g. invalid payload schema). Skips remaining retry attempts and
    goes straight to DLQ instead of wasting retry_delay cycles.
    """
