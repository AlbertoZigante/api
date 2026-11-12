"""Pure-ASGI middlewares (no BaseHTTPMiddleware: it would buffer request bodies)."""
import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import error_body
from .rules import RULES_VERSION


class BodySizeLimitMiddleware:
    """Rejects request bodies above `max_bytes` with 413 before they are parsed.

    Checks Content-Length up front, and counts streamed bytes for chunked
    requests that don't declare one.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        started = False
        rejected = False

        async def counting_receive() -> Message:
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    rejected = True
                    # Simulate a disconnect so the app stops reading the body.
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, counting_receive, tracking_send)
        if rejected and not started:
            await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps(error_body("payload_too_large", f"Request body exceeds {self.max_bytes} bytes")).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class RulesVersionMiddleware:
    """Adds `X-Rules-Version` to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-rules-version", RULES_VERSION.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_header)
