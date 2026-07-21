"""Feb-2026 · Marketing Slice M3 — Mustache-style renderer.

Tiny, dependency-free substituter for ``{{dotted.path}}`` tokens.

Non-goals: partials, sections, filters, escaping.  Every campaign
today ships plaintext-with-html so we deliberately do NOT escape by
default; SMS gets a HTML-strip pass at the router boundary.

Returns
-------
``render_template(body, ctx)`` → ``(rendered_str, missing_var_names)``
where ``missing_var_names`` is a sorted list of dotted paths that
were referenced in the template but not present in the context.  The
UI uses this to warn admins about typos before a send.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# ``{{ some.dotted.path }}`` — whitespace optional.  We deliberately
# do NOT match single braces so campaigns using ``{name}`` for their
# own literal templating (rare but seen in the wild) survive.
_TOKEN_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}")


def _dig(ctx: Any, path: str) -> Any:
    """Walk a dotted path in a nested dict.  Returns ``None`` if any
    segment is missing OR the value is None-ish."""
    cur: Any = ctx
    for seg in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            return None
    return cur


def render_template(body: str, ctx: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Substitute every ``{{path}}`` token with its value from ``ctx``.

    A missing path renders as an empty string AND is added to the
    returned ``missing_vars`` list so the caller can surface a warning.
    """
    missing: List[str] = []

    def _repl(m: re.Match[str]) -> str:
        path = m.group(1)
        val = _dig(ctx, path)
        if val is None or val == "":
            missing.append(path)
            return ""
        return str(val)

    if not body:
        return "", missing
    rendered = _TOKEN_PATTERN.sub(_repl, body)
    return rendered, missing


def render_subject_and_body(
    subject: str, body: str, ctx: Dict[str, Any],
) -> Tuple[str, str, List[str]]:
    """Render a subject + body pair using the same context.  The
    ``missing_vars`` list is the UNION of missing vars across both
    surfaces so a preview call surfaces subject typos too."""
    s, s_missing = render_template(subject or "", ctx)
    b, b_missing = render_template(body or "", ctx)
    return s, b, s_missing + b_missing


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """SMS renderer swings a bat at any HTML that leaked in from a
    copy-paste — carriers don't render tags so we send the plaintext
    equivalent.  ``&nbsp;`` collapses to a space; other entities are
    left alone (rare in field-service SMS)."""
    if not text:
        return ""
    stripped = _HTML_TAG_RE.sub("", text)
    return stripped.replace("&nbsp;", " ")


# ═══════════════════════════════════════════════════════════════════════
# Sample-data + variables registry
# ═══════════════════════════════════════════════════════════════════════
DEFAULT_SAMPLE_CONTEXT: Dict[str, Any] = {
    "customer": {
        "first_name": "Sam",
        "last_name": "Preview",
        "full_name": "Sam Preview",
        "email": "sam@example.com",
        "phone": "+1 (555) 010-4444",
        "balance_due": "$142.00",
    },
    "next_service_date": "2026-08-05",
    "next_service_type": "Pool Cleaning",
    "tenant": {
        "name": "Pool & Landscaping of Vistancia",
        "phone": "+1 (623) 555-0100",
        "google_review_url": "https://g.page/r/example/review",
    },
    # Slice F · unsubscribe magic-link is filled in per-recipient at
    # send time by the M5/M6 tick handlers.  Preview renderer shows a
    # dummy path so admins can see the footer placement.
    "unsubscribe_url": "/portal/preferences?token=example",
}


VARIABLES_REGISTRY: List[Dict[str, str]] = [
    {"name": "customer.first_name",       "description": "The customer's first name."},
    {"name": "customer.last_name",        "description": "The customer's last name."},
    {"name": "customer.full_name",        "description": "The customer's full name."},
    {"name": "customer.email",            "description": "The customer's email address."},
    {"name": "customer.phone",            "description": "The customer's phone number."},
    {"name": "customer.balance_due",      "description": "The customer's outstanding balance, currency-formatted."},
    {"name": "next_service_date",         "description": "The date of the customer's next scheduled visit (YYYY-MM-DD)."},
    {"name": "next_service_type",         "description": "The service type of the next visit (e.g. 'Pool Cleaning')."},
    {"name": "tenant.name",               "description": "Your business name."},
    {"name": "tenant.phone",              "description": "Your business phone number."},
    {"name": "tenant.google_review_url",  "description": "Your Google review URL (configured under Settings > Tenant)."},
    {"name": "unsubscribe_url",           "description": "Per-recipient one-click unsubscribe link. Compliance-required in every marketing send."},
]
