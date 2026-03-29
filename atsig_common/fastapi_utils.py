import logging
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .exceptions import (
    NotFoundError,
    ForbiddenError,
    UnauthorizedError,
    BadRequestError,
    ConflictError,
    AtsigError,
)

logger = logging.getLogger("atsig-common")


def setup_exception_handlers(app: FastAPI):

    @app.exception_handler(AtsigError)
    async def atsig_error_handler(_, exc: AtsigError):
        logger.exception(f"AtsigError caught: {exc.message}")

        return JSONResponse(
            status_code=500,
            content={"detail": exc.message},
        )

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(_, exc: ForbiddenError):
        return JSONResponse(status_code=403, content={"detail": exc.message})

    @app.exception_handler(UnauthorizedError)
    async def unauthorized_handler(_, exc: UnauthorizedError):
        return JSONResponse(status_code=401, content={"detail": exc.message})

    @app.exception_handler(BadRequestError)
    async def bad_request_handler(_, exc: BadRequestError):
        return JSONResponse(
            status_code=400,
            content={"detail": exc.message},
        )

    @app.exception_handler(ConflictError)
    async def conflict_handler(_, exc: ConflictError):
        return JSONResponse(
            status_code=409,
            content={"detail": exc.message},
        )
