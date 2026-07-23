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


# ─── Batch 12D · Feb 2026 — missing-tag polish additions ──────────────
def _customer_id(ctx: Dict[str, Any]) -> str:
    return _safe_str((ctx.get("customer") or {}).get("id"))


def _customer_street(ctx: Dict[str, Any]) -> str:
    """Alias for ``CUSTOMER_ADDRESS`` — reads either
    ``customer.address_line_1`` (Phase 8+ contact schema) or
    ``customer.address`` (legacy single-string field)."""
    c = ctx.get("customer") or {}
    return _safe_str(c.get("address_line_1") or c.get("address") or "")


def _tenant_timezone(ctx: Dict[str, Any]) -> str:
    t = ctx.get("tenant") or {}
    return _safe_str(t.get("timezone") or "America/Phoenix")


def _tenant_next_business_day(ctx: Dict[str, Any]) -> str:
    """Formatted next business day in the tenant's timezone. Skips
    Saturday + Sunday. Custom holidays live on
    ``tenant.business_holidays`` as a list of ``"YYYY-MM-DD"`` strings.
    Returned as ``"Mon, Feb 09"`` — the same format as ``TODAY``."""
    from zoneinfo import ZoneInfo
    from datetime import timedelta, datetime as _dt
    tz_name = _tenant_timezone(ctx) or "America/Phoenix"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Phoenix")
    today_local = _dt.now(tz).date()
    holidays = set((ctx.get("tenant") or {}).get("business_holidays") or [])
    d = today_local + timedelta(days=1)
    for _ in range(14):   # cap the search — 2-week runway is generous
        if d.weekday() < 5 and d.isoformat() not in holidays:
            return d.strftime("%a, %b %d")
        d += timedelta(days=1)
    return d.strftime("%a, %b %d")


def _invoice_pay_url(ctx: Dict[str, Any]) -> str:
    """Portal-authenticated pay URL — customer signs in, then lands on
    the invoice detail with the Pay Now modal available. Never
    embeds a token; safe to include in emails that also mention
    login credentials."""
    inv = ctx.get("invoice") or {}
    inv_id = _safe_str(inv.get("id") or inv.get("invoice_id"))
    if not inv_id:
        return ""
    base = (os.environ.get("APP_PUBLIC_URL")
             or os.environ.get("PUBLIC_FRONTEND_ORIGIN")
             or "").rstrip("/")
    if not base:
        return ""
    return f"{base}/portal/invoices/{inv_id}"


def _invoice_pay_magic_url(ctx: Dict[str, Any]) -> str:
    """Public magic-link pay URL — no login required. Uses whatever
    ``ctx['invoice_pay_link']`` the caller (e.g. the invoice send
    path) already built via
    ``services.pay_link_builder.build_invoice_pay_link``. Falls back
    to the portal URL if no magic link was provided."""
    return (_safe_str(ctx.get("invoice_pay_link"))
             or _invoice_pay_url(ctx))


def _estimate_accept_url(ctx: Dict[str, Any]) -> str:
    """Public magic-link accept URL for the estimate viewer. Reads
    ``ctx['estimate_accept_link']`` when populated by the estimate
    send path; falls back to the (already-registered)
    ``ESTIMATE_LINK`` value on ``ctx['estimate']['view_url']``."""
    if ctx.get("estimate_accept_link"):
        return _safe_str(ctx.get("estimate_accept_link"))
    est = ctx.get("estimate") or {}
    return _safe_str(est.get("view_url") or est.get("public_url") or "")


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


# Phase 11 · Feb 2026 — Equipment Service Tracker resolvers. Resolve
# against ``ctx['equipment_tracker']`` — outside that scope they
# resolve empty, which lands the token in ``unresolved_tokens`` when
# ``missing="placeholder"`` mode is used by the frontend banner.
def _equipment_type(ctx: Dict[str, Any]) -> str:
    et = ctx.get("equipment_tracker") or {}
    return _safe_str(et.get("type_label") or "")


def _equipment_last_cleaned_date(ctx: Dict[str, Any]) -> str:
    et = ctx.get("equipment_tracker") or {}
    return _safe_str(et.get("last_cleaned_at_pretty") or et.get("last_cleaned_at") or "")


def _equipment_due_date(ctx: Dict[str, Any]) -> str:
    et = ctx.get("equipment_tracker") or {}
    return _safe_str(et.get("due_at_pretty") or et.get("due_at") or "")


def _equipment_interval_months(ctx: Dict[str, Any]) -> str:
    et = ctx.get("equipment_tracker") or {}
    v = et.get("interval_months")
    try:
        return str(int(v)) if v is not None else ""
    except (TypeError, ValueError):
        return ""


# Phase 10 · Feb 2026 — Referral credit resolvers. Resolve against
# ``ctx['referral']`` — outside that scope they resolve empty and
# land in ``unresolved_tokens`` when ``missing="placeholder"``.
def _referral_friend_name(ctx: Dict[str, Any]) -> str:
    r = ctx.get("referral") or {}
    return _safe_str(r.get("friend_first_name") or r.get("friend_name") or "")


def _referral_credit_amount(ctx: Dict[str, Any]) -> str:
    r = ctx.get("referral") or {}
    cents = r.get("credit_amount_cents")
    if cents is None:
        return ""
    try:
        return f"${float(cents) / 100.0:,.2f}"
    except (TypeError, ValueError):
        return ""


def _referral_eligible_date(ctx: Dict[str, Any]) -> str:
    r = ctx.get("referral") or {}
    return _safe_str(r.get("eligible_at_pretty") or r.get("eligible_at") or "")


def _customer_credit_balance(ctx: Dict[str, Any]) -> str:
    c = ctx.get("customer") or {}
    cents = c.get("credits_balance_cents")
    if cents is None:
        return ""
    try:
        return f"${float(cents) / 100.0:,.2f}"
    except (TypeError, ValueError):
        return ""


# ═══════════════════════════ Catalogue ═══════════════════════════════
MERGE_TAGS: List[Dict[str, Any]] = [
    # ─── Job / Service
    {"token": "SERVICE_NAME", "label": "Service Name",
     "category": "Job",
     "description": "The service being performed — pulled from the job's "
                     "service_template.name (or recurring template name), "
                     "falling back to service_type / job title.",
     "resolver": lambda ctx: (
        ((ctx or {}).get("job") or {}).get("service_template", {}).get("name")
        or ((ctx or {}).get("job") or {}).get("service_name")
        or ((ctx or {}).get("job") or {}).get("service_type")
        or ((ctx or {}).get("job") or {}).get("title")
        or ((ctx or {}).get("service_name") or "")
     )},
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
    # Batch 12D · Feb 2026 — polish additions.
    {"token": "CUSTOMER_STREET", "label": "Street (alias)",
     "category": "Customer",
     "description": ("Alias for CUSTOMER_ADDRESS. Reads "
                       "``address_line_1`` (Phase 8+ contact schema) "
                       "or falls back to the legacy ``address`` field."),
     "resolver": _customer_street},
    {"token": "CUSTOMER_ID", "label": "Customer ID",
     "category": "Customer",
     "description": ("Raw customer record id — useful for admin-facing "
                       "templates and internal audit tools. Not for "
                       "customer-facing bodies."),
     "resolver": _customer_id},

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
    # Batch 12D · Feb 2026 — expose tenant timezone + next business day
    # to send-time templates (used by scheduling + reminder bodies).
    {"token": "TENANT_TIMEZONE", "label": "Tenant Timezone",
     "category": "Company",
     "description": ("IANA timezone name for the tenant, fallback "
                       "``America/Phoenix``. Useful when signing off "
                       "an email with a time-of-day hint."),
     "resolver": _tenant_timezone},
    {"token": "TENANT_NEXT_BUSINESS_DAY", "label": "Next Business Day",
     "category": "Company",
     "description": ("Formatted next business day in the tenant's "
                       "timezone. Skips Sat/Sun and any dates listed "
                       "on ``tenant.business_holidays``."),
     "resolver": _tenant_next_business_day},

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
    # Batch 12D · Feb 2026 — canonical single-invoice pay URLs.
    {"token": "INVOICE_PAY_URL", "label": "Pay URL (portal)",
     "category": "Invoice",
     "description": ("Portal-authenticated URL to the invoice detail "
                       "page. Requires the customer to log in — safe "
                       "to reuse in emails that also mention creds."),
     "resolver": _invoice_pay_url},
    {"token": "INVOICE_PAY_MAGIC_URL", "label": "Pay URL (magic link)",
     "category": "Invoice",
     "description": ("Public magic-link pay URL — no login required. "
                       "Requires the send path to have populated "
                       "``ctx['invoice_pay_link']`` via the pay-link "
                       "builder; falls back to the portal URL when "
                       "unavailable."),
     "resolver": _invoice_pay_magic_url},

    {"token": "ESTIMATE_ACCEPT_URL", "label": "Estimate Accept URL",
     "category": "Estimate",
     "description": ("Public magic-link accept URL for the estimate "
                       "viewer. Populated by the estimate send path "
                       "via ``ctx['estimate_accept_link']``; falls "
                       "back to ESTIMATE_LINK when absent."),
     "resolver": _estimate_accept_url},

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

    # ─── Equipment (Phase 11 · Feb 2026)
    # Resolves against ``ctx['equipment_tracker']``. Empty (and added
    # to the unresolved-tokens list) when rendered outside a tracker
    # context — e.g. a generic invoice email that accidentally embeds
    # ``{{EQUIPMENT_TYPE}}``.
    {"token": "EQUIPMENT_TYPE", "label": "Equipment Type",
     "category": "Equipment",
     "description": 'Human-readable equipment label — "Filter", "Salt Cell", etc.',
     "resolver": _equipment_type},
    {"token": "EQUIPMENT_LAST_CLEANED_DATE", "label": "Last Cleaned",
     "category": "Equipment",
     "description": "Date the equipment was last cleaned, formatted per tenant.",
     "resolver": _equipment_last_cleaned_date},
    {"token": "EQUIPMENT_DUE_DATE", "label": "Due Date",
     "category": "Equipment",
     "description": "Next scheduled cleaning date, formatted per tenant.",
     "resolver": _equipment_due_date},
    {"token": "EQUIPMENT_INTERVAL_MONTHS", "label": "Interval (months)",
     "category": "Equipment",
     "description": "Cadence in whole months (e.g. 3 for filters, 12 for salt cells).",
     "resolver": _equipment_interval_months},

    # ─── Referral credits (Phase 10 · Feb 2026)
    # Resolves against ``ctx['referral']`` (per-referral scope). The
    # customer balance tag reads from ``ctx['customer']`` (already
    # populated by ``render_context``).
    {"token": "REFERRAL_FRIEND_NAME", "label": "Referred Friend",
     "category": "Referrals",
     "description": "First name of the referred customer.",
     "resolver": _referral_friend_name},
    {"token": "REFERRAL_CREDIT_AMOUNT", "label": "Credit Amount",
     "category": "Referrals",
     "description": "Referral credit amount, formatted (e.g. $25.00).",
     "resolver": _referral_credit_amount},
    {"token": "REFERRAL_ELIGIBLE_DATE", "label": "Eligible Date",
     "category": "Referrals",
     "description": "Date the referral first became eligible for credit.",
     "resolver": _referral_eligible_date},
    {"token": "CUSTOMER_CREDIT_BALANCE", "label": "Credit Balance",
     "category": "Referrals",
     "description": "Customer's current account credit balance, formatted.",
     "resolver": _customer_credit_balance},

    # ─── Add-card magic link (Phase 12 · Feb 2026)
    # Reads ``ctx['add_card_link']`` — populated by the send path in
    # ``routers.customers.send_card_add_link`` when firing the
    # transactional email + SMS.
    {"token": "ADD_CARD_LINK", "label": "Add-Card Link",
     "category": "Payments",
     "description": ("Public magic link to the SetupIntent page for "
                       "saving a card. Expires in 30 days."),
     "resolver": lambda ctx: _safe_str(ctx.get("add_card_link") or "")},

    # ─── Batch 12C · Feb 2026 — Ambiguous Stripe-match digest tags.
    # Populated by ``services.stripe_customer_sync_cron._fire_ambiguous_alert``
    # when a scheduled sync surfaces > 0 rows admins need to resolve.
    {"token": "AMBIGUOUS_MATCH_COUNT", "label": "Ambiguous Match Count",
     "category": "Payments",
     "description": ("Number of CRM customers whose Stripe cross-"
                       "reference produced multiple candidates."),
     "resolver": lambda ctx: _safe_str(ctx.get("ambiguous_match_count") or 0)},
    {"token": "AMBIGUOUS_MATCH_SAMPLE", "label": "Ambiguous Match Sample",
     "category": "Payments",
     "description": ("Comma-joined preview of the first 3 ambiguous "
                       "customer names, for the digest email/SMS body."),
     "resolver": lambda ctx: _safe_str(
         ctx.get("ambiguous_match_sample") or "")},
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

        # Phase 9D · Feb 2026 — cascade order (most-specific wins):
        #   1. Explicit flat-key override in the ctx (bare or flat-dotted).
        #      This lets legacy callers pass a precomputed value that
        #      would otherwise be masked by a catalog resolver's default.
        #   2. Nested-dotted lookup (``{{customer.first_name}}`` →
        #      ``ctx["customer"]["first_name"]``).
        #   3. Uppercase catalog resolver (Phase 9 canonical resolvers
        #      operate on the nested ctx shape).
        # A resolved value at any level short-circuits the cascade.

        # 1) Explicit flat-key override (bare or dotted string key).
        if isinstance(ctx, dict):
            for key in (raw, raw.lower()):
                if key in ctx:
                    v = ctx.get(key)
                    if v not in (None, ""):
                        return _safe_str(v)

        # 2) Nested-dotted lookup.
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

        # 3) Uppercase catalog resolver.
        resolver = _TAG_INDEX.get(upper)
        if resolver is not None:
            try:
                val = resolver(ctx)
            except Exception:
                val = None
            if val not in (None, ""):
                return _safe_str(val)

        # Unresolved after full cascade.
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
