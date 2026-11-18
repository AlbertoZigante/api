"""Pure-ASGI middlewares (no BaseHTTPMiddleware: it would buffer request bodies)."""
import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import error_body
from .logs import log_event
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


_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class AccessLogMiddleware:
    """Request id (accepted from X-Request-ID when well-formed, else generated; echoed on the response) + ONE
    structured log line per request: method, path (no query string), status, duration, client, caller identity,
    auth error code. Never bodies, never credentials."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {**message, "headers": [*message.get("headers", []), (b"x-request-id", request_id.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            state = scope.get("state", {})
            principal = state.get("principal")
            client = scope.get("client")
            log_event(
                "request",
                logging.ERROR if status >= 500 else logging.WARNING if status in (401, 429) else logging.INFO,
                requestId=request_id, method=scope["method"], path=scope["path"], status=status,
                ms=round((time.perf_counter() - started) * 1000, 1), client=client[0] if client else None,
                caller=principal.label if principal else None, authError=state.get("auth_error"),
            )
