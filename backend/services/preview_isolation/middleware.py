"""Preview isolation · ASGI middleware for JSON body routes.

The middleware installs ONCE on the FastAPI app in ``server.py``:

    app.add_middleware(PreviewMiddleware)

On production env, it's a pass-through (the ``is_production_env()``
check at __call__ short-circuits before any body work). On preview
env, for every request whose path matches a registered PII-ingress
route AND whose Content-Type is ``application/json``, the middleware:

1. Buffers the request body.
2. Parses JSON (bails out on non-JSON or malformed input — the
   handler's own validation will 400 it).
3. Recurses through dicts + lists via ``sanitize_pii_payload``, which
   maps every known PII key to its synthetic equivalent and raises
   ``PIIIngressRejected`` on live Stripe tokens / SSN / CC / DL.
4. Re-emits the sanitized body as a new ASGI ``http.request`` stream
   to the handler.

Non-JSON ingress (CSV strings, multipart file uploads, PDFs) stays
with explicit per-handler ``sanitize_csv_rows(...)`` /
``sanitize_pdf_extracted_rows(...)`` calls — the middleware can't
know the field semantics of an arbitrary multipart form.

Rejected requests short-circuit with a 400 JSON body:

    {"detail": {"code": "pii.ingress_rejected",
                 "reason": "<ssn|cc|live_stripe_token|...>",
                 "field": "<name>"}}
"""
from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable

from starlette.types import ASGIApp, Receive, Scope, Send

from .config import is_production_env
from .decorator import PIIIngressRejected, sanitize_pii_payload
from .registry import (
    PII_INGRESS_REGISTRY,
    kind_for_path,
    path_matches_registry,
)

_log = logging.getLogger(__name__)


class PreviewMiddleware:
    """ASGI middleware — no base class, pure callable per Starlette's
    protocol. See module docstring."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if is_production_env():
            # Pass-through. Decorator must be a strict no-op in
            # production per the brief's non-negotiable guard.
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if method not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        if not path_matches_registry(method, path):
            await self.app(scope, receive, send)
            return

        # Only intercept JSON content-type. Multipart / form / CSV
        # strings flow through to the handler untouched (the handler
        # calls ``sanitize_csv_rows`` / ``sanitize_pdf_extracted_rows``
        # itself).
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        ctype = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            await self.app(scope, receive, send)
            return

        # Buffer the full body — JSON ingress bodies are tiny.
        body_chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.request":
                body_chunks.append(message.get("body", b""))
                more = message.get("more_body", False)
            elif message["type"] == "http.disconnect":
                return
            else:
                more = False
        raw = b"".join(body_chunks)
        if not raw:
            # Empty body — defer to handler.
            await self.app(scope, self._replay(raw), send)
            return

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            await self.app(scope, self._replay(raw), send)
            return

        kind = kind_for_path(method, path)
        try:
            sanitized = sanitize_pii_payload(parsed, kind=kind)
        except PIIIngressRejected as exc:
            await _emit_400(send, exc)
            return

        new_body = json.dumps(sanitized).encode("utf-8")
        # Update Content-Length if the client sent one.
        new_headers = []
        for k, v in scope.get("headers", []):
            if k.lower() == b"content-length":
                new_headers.append((k, str(len(new_body)).encode()))
            else:
                new_headers.append((k, v))
        scope = {**scope, "headers": new_headers}

        await self.app(scope, self._replay(new_body), send)

    @staticmethod
    def _replay(body: bytes) -> Receive:
        """Return a ``receive`` callable that yields the sanitized
        body ONCE then blocks forever on subsequent calls.

        Starlette / FastAPI DO call ``receive()`` after the body is
        consumed — they wait for an ``http.disconnect`` to know
        when to abort an in-flight stream. If we return
        ``http.disconnect`` eagerly, downstream middleware (e.g.
        logging / observability wrappers) interprets that as a
        client abort and short-circuits the response pipeline,
        producing a half-written response + a Content-Length
        mismatch on the wire.

        The standard ASGI pattern for a replay-and-done receive is
        to await a Future that never resolves, so the inner
        handlers block indefinitely waiting for the next client
        message (which never comes because we're playing back a
        buffered body, not a live stream)."""
        import asyncio
        emitted = {"done": False}
        done_future: asyncio.Future = asyncio.get_event_loop().create_future()

        async def _receive():
            if not emitted["done"]:
                emitted["done"] = True
                return {"type": "http.request", "body": body, "more_body": False}
            # Block forever — mirrors a quiescent HTTP/1.1 keep-alive
            # connection with no further client bytes to deliver.
            return await done_future

        return _receive


async def _emit_400(send: Send, exc: PIIIngressRejected) -> None:
    payload = json.dumps({
        "detail": {
            "code": "pii.ingress_rejected",
            "reason": exc.reason,
            "field": exc.field,
        }
    }).encode()
    await send({
        "type": "http.response.start",
        "status": 400,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": payload})


__all__ = ["PreviewMiddleware"]
