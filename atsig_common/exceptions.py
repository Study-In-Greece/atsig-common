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
