import time
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

    Responsibilities:
    1. Extracts or generates a unique Request ID.
    2. Extracts User ID and Email from the JWT (if present).
    3. Synchronizes this data with both standard logs and Sentry/GlitchTip.
    4. Records custom, context-aware access logs with execution time.
    5. Catches and logs unhandled exceptions before context cleanup to ensure
       error logs contain the correct Request ID and User Email.
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
            # 3. Process the actual endpoint logic and measure execution time
            start_time = time.time()
            response = await call_next(request)
            process_time = time.time() - start_time

            # 4. Write our custom, context-aware access log
            client_ip = request.client.host if request.client else "unknown"
            logger.info(
                f'{client_ip} - "{request.method} {request.url.path}" '
                f"{response.status_code} ({process_time:.3f}s)"
            )

            # Inject Request ID into response headers for client/frontend debugging
            response.headers["X-Request-ID"] = request_id
            return response

        except Exception:
            # 5. Catch unhandled exceptions to log them WITH context before the finally block clears it.
            # We use logger.exception to automatically include the full stack trace.
            logger.exception(
                f"Unhandled exception during {request.method} {request.url.path}"
            )

            # Re-raise the exception so FastAPI can return a 500 response
            # and Sentry/GlitchTip can capture the event.
            raise

        finally:
            # 6. Cleanup context to prevent memory leaks and data mixing across async workers
            request_id_var.reset(token_rid)
            user_id_var.reset(token_uid)
            user_email_var.reset(token_email)

            # Clear Sentry user scope for the next request in this worker
            sentry_sdk.set_user(None)
