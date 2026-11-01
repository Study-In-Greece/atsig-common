import json

from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_DETAIL = "Max file size reached"


class MultipartBodyLimitMiddleware:
    """
    Refuses a multipart/form-data request whose body is larger than max_body_size,
    before the body is received and written to disk.

    The framework only checks the size of an upload after it has stored the whole
    body, so the check has to happen here, on the stream. Other content types are
    not touched.

    Args:
        max_body_size: The largest body in bytes: the file plus the envelope of the
            form (a megabyte is enough).
        status_code: The status of the refusal. 400 by default, because the
            frontends show the `detail` of a 400 as a message. 413 is the precise
            status, for an API whose clients handle it.
        detail: The message of the refusal. The same text the size check of the
            upload uses, so the user sees one message whichever check fires.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_body_size: int,
        status_code: int = 400,
        detail: str = DEFAULT_DETAIL,
    ):
        self.app = app
        self.max_body_size = max_body_size
        self.status_code = status_code
        self.detail = detail

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._is_multipart(scope):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_body_size:
            await self._reject(send)
            return

        received = 0
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_size:
                    rejected = True
                    await self._reject(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            # After the refusal the app may still try to answer: that answer is dropped
            if not rejected:
                await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except ClientDisconnect:
            # The app was reading the body when we cut it: the 400 is already sent,
            # so this is not an error (it would otherwise be logged as one).
            if not rejected:
                raise

    @staticmethod
    def _is_multipart(scope: Scope) -> bool:
        content_type = Headers(scope=scope).get("content-type", "")
        return content_type.lower().startswith("multipart/form-data")

    async def _reject(self, send: Send) -> None:
        body = json.dumps({"detail": self.detail}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
