"""Raw ASGI middleware: request-size cap + per-request Prometheus counter.

Deliberately not ``starlette.middleware.base.BaseHTTPMiddleware`` - that wraps every
response in an anyio task group and measurably slows a large ``TestClient`` suite. A plain
ASGI callable is a few lines and free.
"""

from __future__ import annotations

import json

from archon.config import get_settings
from archon.core.errors import ErrorCode, Recoverability
from archon.core.observability import metrics


class OpsMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        cl = headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > settings.max_request_bytes:
            await _send_413(send, settings.max_request_bytes)
            return

        status_holder = {"code": 500}

        async def _send(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        await self.app(scope, receive, _send)

        if settings.metrics_enabled:
            path = scope.get("path", "")
            route = scope.get("route")
            label = getattr(route, "path", path)
            if label != "/metrics":
                metrics.http_requests.labels(
                    method=scope.get("method", "?"),
                    route=label,
                    status=str(status_holder["code"]),
                ).inc()


async def _send_413(send, cap: int) -> None:
    body = json.dumps({
        "error": {
            "code": ErrorCode.REQUEST_TOO_LARGE.value,
            "message": f"request body exceeds {cap} bytes",
            "context": {"limit_bytes": cap},
            "recoverability": Recoverability.NON_RECOVERABLE.value,
            "suggested_action": "Split the payload or raise ARCHON_MAX_REQUEST_BYTES.",
        }
    }).encode()
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})
