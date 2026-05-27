import uuid
import jwt
import logging
import sentry_sdk
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from atsig_common.logger.context import request_id_var, user_id_var, user_email_var

logger = logging.getLogger(__name__)


class LoggingContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware that populates logging context variables for each HTTP request.
    It extracts or generates a Request ID, extracts User ID and Email from the JWT,
    and synchronizes this data with both standard logs and Sentry/GlitchTip.
    """

    async def dispatch(self, request: Request, call_next):
        # 1. Handle Correlation ID (Request ID)
        # Use provided header if behind a proxy, otherwise generate a new short UUID
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:8])
        token_rid = request_id_var.set(request_id)

        # Inject Request ID into Sentry/GlitchTip scope
        sentry_sdk.set_tag("request_id", request_id)

        # 2. Extract User Info from JWT Token
        user_id = None
        user_email = None
        auth_header = request.headers.get("Authorization")

        if auth_header and auth_header.startswith("Bearer "):
            try:
                token = auth_header.split(" ")[1]
                # Decode without verification just to extract metadata for observability.
                # Actual security validation happens downstream in FastAPI dependencies.
                payload = jwt.decode(token, options={"verify_signature": False})

                user_id = payload.get("sub")
                user_email = payload.get("email")

                # Inject User info into Sentry/GlitchTip scope
                sentry_sdk.set_user({"id": user_id, "email": user_email})

            except Exception as e:
                # Token might be malformed or expired. We ignore it here,
                # letting the Auth dependency reject it later with a 401.
                logger.debug(
                    f"Failed to decode JWT token in observability middleware: {e}"
                )

        # Set context variables for standard python logging
        token_uid = user_id_var.set(user_id)
        token_email = user_email_var.set(user_email)

        try:
            # 3. Process the actual endpoint logic
            response = await call_next(request)

            # Inject Request ID into response headers for client/frontend debugging
            response.headers["X-Request-ID"] = request_id
            return response

        finally:
            # 4. Cleanup context to prevent memory leaks across async workers
            request_id_var.reset(token_rid)
            user_id_var.reset(token_uid)
            user_email_var.reset(token_email)

            # Clear Sentry user scope for the next request in this worker
            sentry_sdk.set_user(None)
