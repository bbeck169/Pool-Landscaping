"""Phase 9 · Feb 2026 — Canonical merge-tag registry + renderer.

Central catalogue of every merge tag the marketing / transactional
send-time code can substitute at render time. Ships two public entry
points:

* ``MERGE_TAGS`` — the registry (list of dicts). Grouped by
  ``category`` for the UI palette; every entry has a stable
  ``token`` (UPPERCASE_SNAKE), a ``label``, a ``description``, and a
  ``resolver(ctx)`` callable that returns the substituted string.
* ``render_template(body, ctx, missing="empty")`` — the renderer.
  Accepts BOTH ``{{TOKEN}}`` and ``{{ token }}`` styles, case-
  insensitive, whitespace-tolerant, never raises on unknown tokens.
* ``render_context(...)`` — helper that assembles the ``ctx`` dict
  from the caller's Mongo docs (recipient customer, tenant, invoice,
  etc.). Every send-time code path should call this helper so tag
  behavior is uniform across M2 / M5c / portal / referrals / etc.

The old ``services/marketing/render.py`` Mustache renderer keeps
working for legacy ``{{customer.first_name}}`` tags — Phase 9 layers
UPPERCASE tags on top without removing the legacy path.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

_TAG_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def _customer_name_parts(customer: Dict[str, Any]) -> Tuple[str, str]:
    name = _safe_str(customer.get("name") or "").strip()
    if not name:
        return "", ""
    parts = name.split(None, 1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


def _open_balance(customer: Dict[str, Any]) -> str:
    v = customer.get("open_balance") or customer.get("balance_due") or 0
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


# ═══════════════════════════ Resolvers ═══════════════════════════════
def _res(ctx_key: str, sub_key: str, transform: Optional[Callable] = None):
    """Factory: return a resolver that pulls ``ctx[ctx_key][sub_key]``
    (or an empty string) and optionally transforms it."""
    def _r(ctx: Dict[str, Any]) -> str:
        obj = ctx.get(ctx_key) or {}
        val = obj.get(sub_key) if isinstance(obj, dict) else None
        s = _safe_str(val)
        if transform:
            try:
                return transform(s, ctx)
            except Exception:
                return ""
        return s
    return _r


def _customer_first(ctx: Dict[str, Any]) -> str:
    return _customer_name_parts(ctx.get("customer") or {})[0]


def _customer_last(ctx: Dict[str, Any]) -> str:
    return _customer_name_parts(ctx.get("customer") or {})[1]


def _customer_full(ctx: Dict[str, Any]) -> str:
    return _safe_str((ctx.get("customer") or {}).get("name"))


def _customer_balance(ctx: Dict[str, Any]) -> str:
    return _open_balance(ctx.get("customer") or {})


def _company_name(ctx: Dict[str, Any]) -> str:
    return _safe_str((ctx.get("tenant") or {}).get("name"))


def _company_email(ctx: Dict[str, Any]) -> str:
    t = ctx.get("tenant") or {}
    return _safe_str(t.get("support_email") or t.get("email") or "")


def _company_phone(ctx: Dict[str, Any]) -> str:
    t = ctx.get("tenant") or {}
    return _safe_str(t.get("support_phone_number") or t.get("phone") or "")


def _current_month(ctx: Dict[str, Any]) -> str:
    return date.today().strftime("%B")


def _current_year(ctx: Dict[str, Any]) -> str:
    return str(date.today().year)


def _today(ctx: Dict[str, Any]) -> str:
    return date.today().strftime("%b %d, %Y")


def _portal_link(ctx: Dict[str, Any]) -> str:
    base = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
    email = _safe_str((ctx.get("customer") or {}).get("email"))
    if not base:
        return ""
    return f"{base}/portal/login" + (f"?email={email}" if email else "")


def _unsubscribe_link(ctx: Dict[str, Any]) -> str:
    base = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
    email = _safe_str((ctx.get("customer") or {}).get("email"))
    return f"{base}/unsubscribe?email={email}" if base and email else ""


def _invoice_number(ctx: Dict[str, Any]) -> str:
    inv = ctx.get("invoice") or {}
    return _safe_str(inv.get("invoice_number") or inv.get("id") or "")[:8]


def _invoice_total(ctx: Dict[str, Any]) -> str:
    inv = ctx.get("invoice") or {}
    try:
        return f"${float(inv.get('total') or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _invoice_tax(ctx: Dict[str, Any]) -> str:
    inv = ctx.get("invoice") or {}
    try:
        return f"${float(inv.get('tax') or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _invoice_due(ctx: Dict[str, Any]) -> str:
    inv = ctx.get("invoice") or {}
    return _safe_str(inv.get("due_date") or "")[:10]


def _estimate_total(ctx: Dict[str, Any]) -> str:
    est = ctx.get("estimate") or {}
    try:
        return f"${float(est.get('total') or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


# ═══════════════════════════ Catalogue ═══════════════════════════════
MERGE_TAGS: List[Dict[str, Any]] = [
    # ─── Customer
    {"token": "CUSTOMER_FIRST_NAME", "label": "First Name",
     "category": "Customer", "description": "The recipient customer's first name.",
     "resolver": _customer_first},
    {"token": "CUSTOMER_LAST_NAME", "label": "Last Name",
     "category": "Customer", "description": "The recipient customer's last name.",
     "resolver": _customer_last},
    {"token": "CUSTOMER_FULL_NAME", "label": "Full Name",
     "category": "Customer", "description": "The customer's full name as stored.",
     "resolver": _customer_full},
    {"token": "CUSTOMER_EMAIL", "label": "Email",
     "category": "Customer", "description": "The customer's email address.",
     "resolver": _res("customer", "email")},
    {"token": "CUSTOMER_PHONE", "label": "Phone",
     "category": "Customer", "description": "The customer's phone number.",
     "resolver": _res("customer", "phone")},
    {"token": "CUSTOMER_CELL", "label": "Mobile",
     "category": "Customer", "description": "The customer's mobile / cell.",
     "resolver": _res("customer", "phone")},
    {"token": "CUSTOMER_ACCOUNT_BALANCE", "label": "Account Balance",
     "category": "Customer", "description": "Formatted open balance in USD.",
     "resolver": _customer_balance},
    {"token": "CUSTOMER_ADDRESS", "label": "Street Address",
     "category": "Customer", "description": "Customer's primary street address.",
     "resolver": _res("customer", "address")},
    {"token": "CUSTOMER_CITY", "label": "City", "category": "Customer",
     "description": "City parsed from the customer's address.",
     "resolver": _res("customer", "city")},
    {"token": "CUSTOMER_STATE", "label": "State", "category": "Customer",
     "description": "State parsed from the customer's address.",
     "resolver": _res("customer", "state")},
    {"token": "CUSTOMER_ZIP", "label": "ZIP", "category": "Customer",
     "description": "ZIP code parsed from the customer's address.",
     "resolver": _res("customer", "zip")},

    # ─── Company
    {"token": "COMPANY_NAME", "label": "Company Name",
     "category": "Company", "description": "Your company's name.",
     "resolver": _company_name},
    {"token": "COMPANY_OWNER_FIRST_NAME", "label": "Owner First",
     "category": "Company", "description": "Owner's first name from tenant record.",
     "resolver": _res("tenant", "owner_first_name")},
    {"token": "COMPANY_OWNER_LAST_NAME", "label": "Owner Last",
     "category": "Company", "description": "Owner's last name from tenant record.",
     "resolver": _res("tenant", "owner_last_name")},
    {"token": "COMPANY_PHONE", "label": "Company Phone",
     "category": "Company", "description": "Company support phone number.",
     "resolver": _company_phone},
    {"token": "COMPANY_EMAIL", "label": "Company Email",
     "category": "Company", "description": "Company support email.",
     "resolver": _company_email},
    {"token": "COMPANY_WEBSITE", "label": "Company Website",
     "category": "Company", "description": "Company website URL.",
     "resolver": _res("tenant", "website")},

    # ─── Estimate
    {"token": "ESTIMATE_TOTAL", "label": "Estimate Total",
     "category": "Estimate", "description": "Formatted total of the estimate.",
     "resolver": _estimate_total},
    {"token": "ESTIMATE_NUMBER", "label": "Estimate Number",
     "category": "Estimate", "description": "Short id of the estimate.",
     "resolver": lambda c: _safe_str((c.get("estimate") or {}).get("id"))[:8]},
    {"token": "ESTIMATE_LINK", "label": "Estimate Link",
     "category": "Estimate", "description": "Public-facing link to the estimate.",
     "resolver": lambda c: _safe_str((c.get("estimate") or {}).get("public_url"))},
    {"token": "ESTIMATE_EDIT_LINK", "label": "Estimate Edit Link",
     "category": "Estimate", "description": "Admin edit link to the estimate.",
     "resolver": lambda c: _safe_str((c.get("estimate") or {}).get("edit_url"))},
    {"token": "ESTIMATE_CHANGES", "label": "Estimate Changes",
     "category": "Estimate", "description": "Human summary of latest estimate changes.",
     "resolver": lambda c: _safe_str((c.get("estimate") or {}).get("changes_summary"))},

    # ─── Invoice
    {"token": "INVOICE_TOTAL", "label": "Invoice Total",
     "category": "Invoice", "description": "Formatted invoice total.",
     "resolver": _invoice_total},
    {"token": "INVOICE_TAX", "label": "Invoice Tax",
     "category": "Invoice", "description": "Formatted invoice tax amount.",
     "resolver": _invoice_tax},
    {"token": "INVOICE_NUMBER", "label": "Invoice Number",
     "category": "Invoice", "description": "Short invoice identifier.",
     "resolver": _invoice_number},
    {"token": "INVOICE_DUE_DATE", "label": "Invoice Due Date",
     "category": "Invoice", "description": "Invoice due date (YYYY-MM-DD).",
     "resolver": _invoice_due},
    {"token": "INVOICES_LINKS", "label": "All Invoice Links",
     "category": "Invoice", "description": "Bullet list of pay links.",
     "resolver": lambda c: _safe_str((c.get("invoice") or {}).get("all_links_html"))},

    # ─── Payment
    {"token": "PAYMENT_AMOUNT", "label": "Payment Amount",
     "category": "Payment", "description": "Formatted payment amount.",
     "resolver": lambda c: (
         f"${float((c.get('payment') or {}).get('amount') or 0):,.2f}"
     )},
    {"token": "PAYMENT_METHOD", "label": "Payment Method",
     "category": "Payment", "description": "Card brand / ACH label.",
     "resolver": _res("payment", "method")},
    {"token": "PAYMENT_DATE", "label": "Payment Date",
     "category": "Payment", "description": "Payment received date (YYYY-MM-DD).",
     "resolver": lambda c: _safe_str((c.get("payment") or {}).get("date"))[:10]},
    {"token": "RECEIPT_LINK", "label": "Receipt Link (Customer)",
     "category": "Payment", "description": "Customer-facing receipt URL.",
     "resolver": _res("payment", "receipt_url")},
    {"token": "RECEIPT_ADMIN_LINK", "label": "Receipt Link (Admin)",
     "category": "Payment", "description": "Admin console receipt URL.",
     "resolver": _res("payment", "admin_receipt_url")},

    # ─── Portal
    {"token": "CUSTOMER_PORTAL_LINK", "label": "Portal Link",
     "category": "Portal", "description": "Customer portal login URL.",
     "resolver": _portal_link},
    {"token": "CUSTOMER_PORTAL_ADD_CREDIT_CARD_LINK", "label": "Add Card Link",
     "category": "Portal", "description": "Deep-link to add a credit card.",
     "resolver": lambda c: (_portal_link(c) or "") + "#add-card"},
    {"token": "UNSUBSCRIBE", "label": "Unsubscribe Link",
     "category": "Portal", "description": "Per-recipient unsubscribe URL.",
     "resolver": _unsubscribe_link},
    {"token": "REVIEW_PAGE", "label": "Review Page",
     "category": "Portal", "description": "Public review-request page URL.",
     "resolver": _res("tenant", "google_review_url")},
    {"token": "DOCUMENT_LINK", "label": "Document Link",
     "category": "Portal", "description": "Attached document URL.",
     "resolver": _res("document", "url")},
    {"token": "WORK_REQUEST_FORM", "label": "Work Request Form",
     "category": "Portal", "description": "URL of the public work request form.",
     "resolver": _res("tenant", "work_request_form_url")},

    # ─── Event
    {"token": "EVENT_TITLE", "label": "Event Title",
     "category": "Event", "description": "Title of the scheduled event.",
     "resolver": _res("event", "title")},
    {"token": "EVENT_DATE", "label": "Event Date",
     "category": "Event", "description": "Scheduled date of the event.",
     "resolver": lambda c: _safe_str((c.get("event") or {}).get("date"))[:10]},
    {"token": "EVENT_PROPERTY_ADDRESS", "label": "Event Property Address",
     "category": "Event", "description": "Property address for the event.",
     "resolver": _res("event", "property_address")},
    {"token": "EVENT_SCHEDULED_TIME", "label": "Event Time",
     "category": "Event", "description": "Scheduled time (HH:MM).",
     "resolver": _res("event", "time")},
    {"token": "EVENT_NOTES", "label": "Event Notes",
     "category": "Event", "description": "Free-form notes on the event.",
     "resolver": _res("event", "notes")},

    # ─── Employee
    {"token": "EMPLOYEE_FIRST_NAME", "label": "Employee First",
     "category": "Employee", "description": "Assigned employee's first name.",
     "resolver": lambda c: _customer_name_parts(c.get("employee") or {})[0]},
    {"token": "EMPLOYEE_LAST_NAME", "label": "Employee Last",
     "category": "Employee", "description": "Assigned employee's last name.",
     "resolver": lambda c: _customer_name_parts(c.get("employee") or {})[1]},
    {"token": "CALL_NOTES", "label": "Call Notes",
     "category": "Employee", "description": "Latest call notes summary.",
     "resolver": _res("event", "call_notes")},

    # ─── System
    {"token": "CURRENT_MONTH", "label": "Current Month",
     "category": "System", "description": "Full name of the current month.",
     "resolver": _current_month},
    {"token": "CURRENT_YEAR", "label": "Current Year",
     "category": "System", "description": "Current 4-digit year.",
     "resolver": _current_year},
    {"token": "TODAY", "label": "Today's Date",
     "category": "System", "description": "Today's date, Mon DD YYYY.",
     "resolver": _today},
    {"token": "NOTES_TO_DISPATCHER", "label": "Notes to Dispatcher",
     "category": "System", "description": "Free-form dispatcher notes on the job.",
     "resolver": _res("event", "dispatch_notes")},
    {"token": "PROPERTY_NOT_SERVICED_REASON", "label": "Not Serviced Reason",
     "category": "System", "description": "Reason a scheduled service was skipped.",
     "resolver": _res("event", "not_serviced_reason")},
]

_TAG_INDEX: Dict[str, Callable] = {t["token"].upper(): t["resolver"]
                                        for t in MERGE_TAGS}


# ═══════════════════════════ Renderer ════════════════════════════════
def render_template(body: str, ctx: Optional[Dict[str, Any]] = None,
                     missing: str = "empty") -> Tuple[str, List[str]]:
    """Render ``body`` by substituting every ``{{TOKEN}}`` for its
    resolved value from ``ctx``.

    Returns ``(rendered_string, unresolved_tokens_list)``.

    * Case-insensitive: ``{{customer_first_name}}`` matches
      ``CUSTOMER_FIRST_NAME``.
    * Whitespace-tolerant: ``{{ CUSTOMER_FIRST_NAME }}`` is fine.
    * ``missing`` controls unknown-token behavior:
      * ``"empty"`` (default) → replaced with an empty string.
      * ``"placeholder"`` → replaced with ``[MISSING: TOKEN]``.
    * NEVER raises; a resolver that itself blows up produces an empty
      substitution and the token is added to the unresolved list.
    """
    if body is None:
        return "", []
    ctx = ctx or {}
    unresolved: List[str] = []

    def _sub(match: "re.Match[str]") -> str:
        raw = match.group(1)
        upper = raw.upper()
        # Phase 9 uppercase token match.
        resolver = _TAG_INDEX.get(upper)
        if resolver is not None:
            try:
                val = resolver(ctx)
            except Exception:
                unresolved.append(upper)
                return "" if missing == "empty" else f"[MISSING: {upper}]"
            if val is None or val == "":
                # Resolver returned nothing — treat as unresolved for
                # UI reporting, but still substitute empty by default.
                unresolved.append(upper)
                return "" if missing == "empty" else f"[MISSING: {upper}]"
            return _safe_str(val)
        # Legacy dotted-path form ``{{customer.first_name}}``.
        if "." in raw:
            parts = raw.split(".")
            cursor: Any = ctx
            for p in parts:
                if isinstance(cursor, dict) and p in cursor:
                    cursor = cursor[p]
                else:
                    cursor = None
                    break
            if cursor not in (None, ""):
                return _safe_str(cursor)
        # Unknown tag.
        unresolved.append(upper)
        return "" if missing == "empty" else f"[MISSING: {upper}]"

    rendered = _TAG_RE.sub(_sub, body)
    return rendered, sorted(set(unresolved))


def render_context(*, customer: Optional[Dict[str, Any]] = None,
                    tenant: Optional[Dict[str, Any]] = None,
                    invoice: Optional[Dict[str, Any]] = None,
                    estimate: Optional[Dict[str, Any]] = None,
                    payment: Optional[Dict[str, Any]] = None,
                    employee: Optional[Dict[str, Any]] = None,
                    event: Optional[Dict[str, Any]] = None,
                    document: Optional[Dict[str, Any]] = None,
                    **extra: Any) -> Dict[str, Any]:
    """Build a render context dict from the caller's Mongo docs. Every
    Phase 9 send-time code path assembles its ctx via this helper so
    tag behavior stays uniform."""
    return {
        "customer": customer or {},
        "tenant": tenant or {},
        "invoice": invoice or {},
        "estimate": estimate or {},
        "payment": payment or {},
        "employee": employee or {},
        "event": event or {},
        "document": document or {},
        **extra,
    }


def catalog_grouped() -> Dict[str, List[Dict[str, Any]]]:
    """Return the merge-tag registry grouped by category, minus the
    resolver callables (JSON-serialisable). Used by
    ``GET /api/marketing/merge-tags``."""
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for t in MERGE_TAGS:
        by_cat.setdefault(t["category"], []).append({
            "token": t["token"],
            "label": t["label"],
            "description": t["description"],
        })
    return by_cat
