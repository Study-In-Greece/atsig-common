from fastapi import FastAPI
from fastapi.responses import JSONResponse
from .exceptions import NotFoundError, ForbiddenError, UnauthorizedError


def setup_exception_handlers(app: FastAPI):
    @app.exception_handler(NotFoundError)
    async def not_found_handler(_, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(_, exc: ForbiddenError):
        return JSONResponse(status_code=403, content={"detail": exc.message})

    @app.exception_handler(UnauthorizedError)
    async def unauthorized_handler(_, exc: UnauthorizedError):
        return JSONResponse(status_code=401, content={"detail": exc.message})
