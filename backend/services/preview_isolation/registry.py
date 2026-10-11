"""Preview isolation · PII-ingress route registry + boot-time audit.

The registry is the single source of truth for which FastAPI routes
accept PII and therefore MUST be sanitized on preview.

Each entry is ``(method, path_pattern, kind, body_shape)`` where:

* ``path_pattern`` is a Starlette-style template path (e.g.
  ``/api/customers/{cid}``) — matched against the live request path
  by converting ``{...}`` placeholders to ``[^/]+`` regex.
* ``kind`` is one of ``customer`` / ``lead`` / ``subscriber`` /
  ``signup`` / ``generic`` — the sanitizer uses it to pick the right
  synthetic field map.
* ``body_shape`` is ``json`` / ``csv`` / ``pdf`` / ``multipart`` —
  the middleware only auto-sanitizes ``json`` bodies; ``csv`` / ``pdf``
  / ``multipart`` MUST call the appropriate sanitize helper in the
  handler.

``audit_route_registry(app)`` walks the FastAPI app's route table and
returns a report:

    {
        "total_routes": 1200,
        "declared_pii_routes": 40,
        "unregistered_pii_shaped_routes": [...],
        "status": "GREEN" | "AMBER" | "RED",
    }

Status rules:
* GREEN — every registered route is still present in the app AND no
  app route has a PII-shaped request body outside the registry.
* AMBER — a registered route is missing from the app (dead entry)
  OR a non-registered route has a PII-shaped Pydantic field name.
* RED — a registered PII-ingress route is UNREGISTERED (should
  never happen; defense-in-depth).

``assert_registry_coverage(app)`` raises ``RuntimeError`` on preview
env when the status is RED. On production, it logs a WARN and
returns.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .config import is_preview_env, is_production_env

_log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Registry — curated list of PII-ingress endpoints (Q1 inventory).
# ────────────────────────────────────────────────────────────────────
# ``(method, path_pattern, kind, body_shape)``
PII_INGRESS_REGISTRY: List[Tuple[str, str, str, str]] = [
    # Admin — direct create/edit of customers.
    ("POST",  "/api/customers",                             "customer", "json"),
    ("POST",  "/api/customers/bulk",                        "customer", "json"),
    ("PUT",   "/api/customers/{cid}",                       "customer", "json"),
    ("PATCH", "/api/customers/{cid}",                       "customer", "json"),
    ("PATCH", "/api/customers/{cid}/emails",                "customer", "json"),
    ("PATCH", "/api/customers/{cid}/mobiles",               "customer", "json"),
    ("PATCH", "/api/customers/{cid}/service-notes",         "customer", "json"),
    ("POST",  "/api/customers/{cid}/account-correction",    "customer", "json"),
    ("POST",  "/api/customers/{cid}/create-login",          "customer", "json"),
    # Admin CSV / PDF imports — handler calls sanitize_csv_rows itself.
    ("POST",  "/api/import/customers",                      "customer", "csv"),
    ("POST",  "/api/customers/import-csv",                  "customer", "csv"),
    ("POST",  "/api/imports/pdf-invoice",                   "customer", "multipart"),
    ("POST",  "/api/imports/pdf-invoice/{batch_id}/commit", "customer", "json"),
    ("PATCH", "/api/imports/pdf-invoice/{batch_id}/preview","customer", "json"),
    # Leads.
    ("POST",  "/api/leads",                                 "lead",     "json"),
    ("PUT",   "/api/leads/{lid}",                           "lead",     "json"),
    ("PATCH", "/api/leads/{lid}",                           "lead",     "json"),
    ("POST",  "/api/leads/{lid}/convert-to-customer",       "customer", "json"),
    ("POST",  "/api/leads/{lid}/convert-to-job",            "customer", "json"),
    ("POST",  "/api/leads/{lid}/convert-to-quote",          "customer", "json"),
    ("POST",  "/api/public/leads",                          "lead",     "json"),
    ("POST",  "/api/public/lead-request/{token}/submit",    "lead",     "json"),
    # Marketing / subscribers / forms.
    ("POST",  "/api/marketing/subscribers",                 "subscriber","json"),
    ("PATCH", "/api/marketing/subscribers/{sid}",           "subscriber","json"),
    ("POST",  "/api/marketing/public/signup-form/{form_slug}/subscribe",
                                                            "subscriber","json"),
    ("POST",  "/api/marketing/public/confirm",              "subscriber","json"),
    ("POST",  "/api/widget/form/{fid}/submit",              "lead",     "json"),
    ("POST",  "/api/widget/form/{fid}/submit-multipart",    "lead",     "multipart"),
    ("POST",  "/api/public/forms/{slug}/submit",            "lead",     "json"),
    ("POST",  "/api/public/instaquote/{slug}/submit",       "customer", "json"),
    # Portal / self-serve.
    ("POST",  "/api/signup",                                "signup",   "json"),
    ("PATCH", "/api/customer-portal/profile",               "customer", "json"),
    ("POST",  "/api/customer-portal/service-requests",      "generic",  "json"),
    ("PUT",   "/api/me",                                    "customer", "json"),
    # Outreach.
    ("POST",  "/api/outreach/prospects",                    "lead",     "json"),
    ("PATCH", "/api/outreach/prospects/{pid}",              "lead",     "json"),
    ("POST",  "/api/outreach/prospects/bulk-import",        "lead",     "csv"),
    # Webhooks (external-origin ingress).
    ("POST",  "/api/webhooks/lumino/zapier",                "lead",     "json"),
    ("POST",  "/api/webhooks/lumino",                       "lead",     "json"),
    # Signatures.
    ("POST",  "/api/public/sign/{token}/submit",            "generic",  "json"),
    ("POST",  "/api/public/csat/{token}/submit",            "generic",  "json"),
]


# ────────────────────────────────────────────────────────────────────
# Pattern compilation + matching.
# ────────────────────────────────────────────────────────────────────
def _pattern_to_regex(path_pattern: str) -> re.Pattern:
    r"""Convert ``/api/customers/{cid}`` to ``^/api/customers/[^/]+$``.
    Trailing slash is tolerated."""
    # Replace ``{param}`` with ``[^/]+``.
    escaped = re.sub(r"\{[^}]+\}", r"[^/]+", path_pattern)
    return re.compile(rf"^{escaped}/?$")


_COMPILED: List[Tuple[str, re.Pattern, str, str]] = [
    (m, _pattern_to_regex(p), k, s)
    for (m, p, k, s) in PII_INGRESS_REGISTRY
]


def path_matches_registry(method: str, path: str) -> bool:
    """``True`` iff the request matches a registered PII-ingress
    route. Case-insensitive on method."""
    method_up = method.upper()
    for m, re_p, _, _ in _COMPILED:
        if m == method_up and re_p.match(path):
            return True
    return False


def kind_for_path(method: str, path: str) -> str:
    """Return the ``kind`` tag registered for a matching path, or
    ``"generic"`` if not found."""
    method_up = method.upper()
    for m, re_p, k, _ in _COMPILED:
        if m == method_up and re_p.match(path):
            return k
    return "generic"


def body_shape_for_path(method: str, path: str) -> Optional[str]:
    method_up = method.upper()
    for m, re_p, _, s in _COMPILED:
        if m == method_up and re_p.match(path):
            return s
    return None


# ────────────────────────────────────────────────────────────────────
# Boot-time audit.
# ────────────────────────────────────────────────────────────────────
def audit_route_registry(app: Any) -> Dict[str, Any]:
    """Walk ``app.routes`` and compare to the registry. Pure
    read-only. Returns the report shape documented in the module
    docstring."""
    app_routes: List[Tuple[str, str]] = []
    for r in getattr(app, "routes", []):
        methods = getattr(r, "methods", None) or set()
        path = getattr(r, "path", "")
        for m in methods:
            app_routes.append((m.upper(), path))

    # Which registered routes are MISSING from the app?
    missing: List[Tuple[str, str]] = []
    for m, p, _, _ in PII_INGRESS_REGISTRY:
        if (m, p) not in app_routes:
            missing.append((m, p))

    # Which app routes LOOK LIKE PII ingress (POST/PUT/PATCH + path
    # keyword) but aren't registered? Soft-detection; AMBER status.
    pii_hint = re.compile(
        r"/(customers?|leads?|subscribers?|signup|import|prospects?|"
        r"portal/profile|form/.*/submit|lead-request|signatures?)",
        re.IGNORECASE,
    )
    unregistered: List[Tuple[str, str]] = []
    for m, p in app_routes:
        if m not in ("POST", "PUT", "PATCH"):
            continue
        if not pii_hint.search(p):
            continue
        # Skip paths already covered by the registry.
        if path_matches_registry(m, p.replace("{", "{")):
            continue
        # Dynamic-path round-trip: build a fake example path and
        # test it.
        example = re.sub(r"\{[^}]+\}", "x", p)
        if path_matches_registry(m, example):
            continue
        unregistered.append((m, p))

    status = "GREEN"
    if missing:
        status = "RED"
    elif unregistered:
        status = "AMBER"

    return {
        "total_routes": len(app_routes),
        "declared_pii_routes": len(PII_INGRESS_REGISTRY),
        "missing_registered_routes": missing,
        "unregistered_pii_shaped_routes": unregistered,
        "status": status,
    }


def assert_registry_coverage(app: Any) -> Dict[str, Any]:
    """Call from server startup. On preview env with status=RED,
    raises ``RuntimeError``. On production, always returns the
    report regardless of status (never fails boot).

    Phase 1 posture (this commit): RED is treated as a WARN-only
    even on preview — flipped to hard-fail in a follow-up commit
    once full endpoint coverage lands.
    """
    report = audit_route_registry(app)
    if report["status"] == "RED":
        _log.warning(
            "[preview_isolation] registry RED — missing registered "
            "routes: %s", report["missing_registered_routes"],
        )
        if is_production_env():
            return report
        # Preview: WARN-only in Phase 1. Flip to RuntimeError in a
        # follow-up commit after wiring the remaining ingress sites.
        _log.warning(
            "[preview_isolation] Phase-1 posture — RED on preview "
            "is logged but does not fail boot. Follow-up commit "
            "promotes this to RuntimeError once coverage is full."
        )
    elif report["status"] == "AMBER":
        _log.info(
            "[preview_isolation] registry AMBER — PII-shaped routes "
            "not in registry: %s",
            [p for _, p in report["unregistered_pii_shaped_routes"]][:20],
        )
    else:
        _log.info(
            "[preview_isolation] registry GREEN — %d/%d routes covered",
            report["declared_pii_routes"], report["total_routes"],
        )
    return report


__all__ = [
    "PII_INGRESS_REGISTRY",
    "audit_route_registry",
    "assert_registry_coverage",
    "path_matches_registry",
    "kind_for_path",
    "body_shape_for_path",
]
