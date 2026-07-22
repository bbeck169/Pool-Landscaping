"""Feb-2026 · Marketing Slice M3 — Mustache-style renderer.

Phase 9D · Feb 2026 — this module is now a THIN ADAPTER that delegates
every render call to :func:`services.marketing.merge_tags.render_template`.
The public function signatures are preserved 1:1 so downstream callers
(`marketing_templates.py`, `marketing_sequences.py`,
`marketing_review_requests.py`, `marketing_forms.py`) do not change.

Behavioral divergences vs. the pre-9D engine (documented so downstream
tests can be re-baselined):

* Missing tokens still render as ``""`` — same as before.
* The ``missing_vars`` list is now derived from the canonical unified
  engine's ``unresolved_tokens`` output. Names may return UPPERCASE
  when they hit the catalog. Downstream code treats this list as a
  warning surface only — no wire-format contracts depend on case.

Non-goals: partials, sections, filters. Every campaign today ships
plaintext-with-html so we deliberately do NOT escape by default; SMS
gets a HTML-strip pass at the router boundary (unchanged).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from services.marketing.merge_tags import render_template as _canonical_render


def render_template(body: str, ctx: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Substitute every ``{{path}}`` token with its value from ``ctx``.

    Missing paths render as empty AND appear in ``missing_vars`` so
    callers can surface warnings. Delegates to the canonical
    :func:`services.marketing.merge_tags.render_template` — the missing
    list is derived by intersecting the input template's tokens (in
    their ORIGINAL case) with the canonical engine's uppercase
    ``unresolved_tokens`` output, so this wrapper preserves the case
    of the raw template.
    """
    if not body:
        return "", []
    rendered, unresolved_upper = _canonical_render(body, ctx or {}, missing="empty")
    upper_set = set(unresolved_upper)
    # Preserve original casing by re-scanning the template.
    raw_missing: List[str] = []
    seen: set = set()
    for m in re.finditer(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}", body):
        raw = m.group(1)
        if raw.upper() in upper_set and raw not in seen:
            raw_missing.append(raw)
            seen.add(raw)
    return rendered, raw_missing


def render_subject_and_body(
    subject: str, body: str, ctx: Dict[str, Any],
) -> Tuple[str, str, List[str]]:
    """Render subject + body under the same context. ``missing_vars`` is
    the UNION across both surfaces so preview surfaces subject typos too."""
    s, s_missing = render_template(subject or "", ctx)
    b, b_missing = render_template(body or "", ctx)
    return s, b, list(s_missing) + list(b_missing)


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """SMS renderer swings a bat at any HTML that leaked in from a
    copy-paste — carriers don't render tags so we send the plaintext
    equivalent. ``&nbsp;`` collapses to a space; other entities are
    left alone (rare in field-service SMS)."""
    if not text:
        return ""
    stripped = _HTML_TAG_RE.sub("", text)
    return stripped.replace("&nbsp;", " ")


# ═══════════════════════════════════════════════════════════════════════
# Sample-data + variables registry — unchanged, referenced by the
# ``/preview`` endpoint's default sample context and the preview picker.
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
