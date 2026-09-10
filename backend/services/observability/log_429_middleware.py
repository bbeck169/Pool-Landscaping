"""Feb-2026 · P0 · 429 observability middleware.

Purpose
-------
Field techs are seeing raw ``429 Too Many Requests`` responses on
the mobile checklist Close-Job flow (``PATCH /api/jobs/{id}/service-report``
+ ``POST /api/jobs/{id}/service-report/submit``). Preview curls show
ZERO 429s on our own handlers, which means the 429 is being minted
either:

  * By our own request handlers on prod under a config we can't see
    from preview (e.g. a tenant BYO-provider cap firing under real
    call volume).
  * By the ingress / WAF layer on prod (Cloudflare / k8s ingress /
    shared-IP quota when multiple techs pile up against the same
    office egress IP at end-of-day).

Regardless of source, we need production observability so ops can
answer three questions quickly when a 429 lands:

    1. WHICH endpoint returned 429?
    2. WHICH tenant + user was affected?
    3. WHAT was the source (our app code or the ingress)?

Behaviour
---------
* Runs on every request. Zero overhead for 2xx responses.
* When status == 429, emits ONE structured log line at WARNING
  level with a ``[429_OBS]`` prefix so ops can grep it:

    [429_OBS] endpoint=PATCH /api/jobs/{jid}/service-report
              tenant=<id> user=<id> role=<role>
              via=<app|ingress> retry_after=<int|-> ...

* Adds a response header ``X-Ratelimit-Source`` (``app`` if the 429
  came from our own code, ``upstream`` if we're just a passthrough)
  so mobile clients + ops dashboards can differentiate.

Wired in ``server.py`` via ``app.add_middleware(Log429Middleware)``.
"""
from __future__ import annotations

import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("pool_crm.observability.429")


class Log429Middleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable,
    ) -> Response:
        response = await call_next(request)
        if response.status_code != 429:
            return response

        # ``request.state`` is populated by our auth deps
        # (``get_current_user`` / ``get_current_tenant``). Some
        # endpoints skip auth (public magic-link), so both may be
        # absent — never blow up here.
        user = getattr(request.state, "user", None) or {}
        tenant = getattr(request.state, "tenant", None) or {}

        # If the 429 carries our own structured detail payload we
        # know we minted it. Otherwise it's coming from an
        # upstream ingress and is a passthrough.
        via = "app"
        try:
            # ``response`` from a Starlette dispatch can be a
            # StreamingResponse (body iterator) or plain Response.
            # We don't buffer the body here — we key on the
            # presence of ``X-Ratelimit-Reason`` which we set on
            # every 429 we mint ourselves (see helper below).
            if "X-Ratelimit-Reason" not in response.headers:
                via = "upstream"
        except Exception:  # noqa: BLE001 — never fail obs
            via = "unknown"

        retry_after = response.headers.get("Retry-After", "-")
        try:
            logger.warning(
                "[429_OBS] endpoint=%s %s tenant=%s user=%s "
                "role=%s via=%s retry_after=%s reason=%s",
                request.method, request.url.path,
                tenant.get("id", "-"),
                user.get("id", "-"),
                user.get("role", "-"),
                via,
                retry_after,
                response.headers.get("X-Ratelimit-Reason", "-"),
            )
        except Exception:  # noqa: BLE001 — never fail obs
            pass

        # Stamp the source header on the way out so mobile + ops
        # can tell app-minted 429s from ingress passthroughs.
        response.headers["X-Ratelimit-Source"] = via
        return response


def mint_429_headers(
    *, reason: str, retry_after_seconds: int | None = None,
) -> dict[str, str]:
    """Helper for callsites that raise HTTPException(429, ...).

    Attach the returned dict as ``headers=`` on the exception so
    the middleware above can distinguish our-own 429s from
    upstream passthroughs, and so mobile clients can back off
    intelligently::

        raise HTTPException(
            status_code=429,
            detail={"error_code": "rate_limited",
                    "reason": "tenant_ai_cap"},
            headers=mint_429_headers(
                reason="tenant_ai_cap", retry_after_seconds=60,
            ),
        )
    """
    h: dict[str, str] = {"X-Ratelimit-Reason": reason}
    if retry_after_seconds is not None:
        h["Retry-After"] = str(int(retry_after_seconds))
    return h
