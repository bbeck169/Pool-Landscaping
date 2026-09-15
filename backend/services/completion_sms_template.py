"""Phase COMM1 · Feb-2026 — Completion SMS template.

Builds the concise SMS sent to the customer when a tech submits a
service report. Pure function; no I/O.

Template:
    ``Hi {first}, your {title} with {business} is complete!
    View your full report and photos here: {portal_link}``

Rules:
  * ``{first}``     — first-name only. Fallback order:
        ``customer.first_name`` →
        first token of ``customer.name`` →
        the literal string ``"there"``.
  * ``{title}``     — human-readable service label. Fallback order:
        ``job.title`` → ``job.service_type`` →
        ``"service"``.
        Trimmed to 60 chars when longer (single-word overflow gets
        an ellipsis so the boundary is visible to the customer).
  * ``{business}``  — ``tenant.name`` (per-tenant; NEVER hard-coded).
        Fallback: ``"your service provider"``.
  * ``{portal_link}`` — passed in verbatim by the caller.

The template contains ZERO chemistry readings, zero numeric values,
and zero date/time details — the portal link owns all of that.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional


_TITLE_MAX = 60
_FALLBACK_FIRST_NAME = "there"
_FALLBACK_TITLE = "service"
_FALLBACK_BUSINESS = "your service provider"


def _first_non_empty(*candidates: Any) -> Optional[str]:
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s:
            return s
    return None


def _pick_first_name(customer: Optional[Mapping[str, Any]]) -> str:
    """Return the customer's first name, then the first token of a
    single ``name`` field, then the literal string ``"there"``."""
    c = customer or {}
    fn = _first_non_empty(c.get("first_name"))
    if fn:
        # Even ``first_name`` may accidentally hold "Diego Ruiz" —
        # take the first whitespace-delimited token defensively.
        return fn.split()[0]
    name = _first_non_empty(c.get("name"))
    if name:
        return name.split()[0]
    return _FALLBACK_FIRST_NAME


def _pick_job_title(job: Optional[Mapping[str, Any]]) -> str:
    """Return the job's human-readable service label, trimmed to
    ``_TITLE_MAX`` chars."""
    j = job or {}
    label = _first_non_empty(j.get("title"), j.get("service_type")) \
        or _FALLBACK_TITLE
    if len(label) > _TITLE_MAX:
        # Preserve the boundary visually — customers rarely inspect
        # SMS carefully, so an ellipsis makes the trim obvious.
        return label[: _TITLE_MAX - 1].rstrip() + "…"
    return label


def _pick_business_name(tenant: Optional[Mapping[str, Any]]) -> str:
    t = tenant or {}
    return _first_non_empty(t.get("name")) or _FALLBACK_BUSINESS


def build_completion_sms_body(
    *,
    tenant: Optional[Mapping[str, Any]],
    job: Optional[Mapping[str, Any]],
    customer: Optional[Mapping[str, Any]],
    portal_link: str,
) -> str:
    """Return the exact SMS body — a single line, no numeric values,
    no chemistry mentions.

    Callers keep the ``portal_link`` builder they already had — this
    helper does not touch magic-link JWT construction.
    """
    first = _pick_first_name(customer)
    title = _pick_job_title(job)
    business = _pick_business_name(tenant)
    return (
        f"Hi {first}, your {title} with {business} is complete! "
        f"View your full report and photos here: {portal_link}"
    )
