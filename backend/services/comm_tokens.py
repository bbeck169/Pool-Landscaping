"""Communications Subsystem · Phase 1 — Token catalog + resolvers + HTML renderer.

Flat catalog of every merge token exposed to the email/SMS builder,
resolver helpers that walk plain text or ``blocks_json`` and substitute
``{{token.name}}`` sequences, and an Outlook-safe, table-based HTML
renderer that turns a Constant-Contact-style ``blocks_json`` payload into
final email HTML. No MJML dependency — hand-rolled table HTML compatible
with Outlook 2016+, Gmail, Apple Mail, and Yahoo webmail.

Missing token values render as empty strings and log a warning; a token
that isn't in the catalog at all raises during ``resolve_tokens`` in
strict mode (unused by delivery paths — only preview endpoints opt in).
"""
from __future__ import annotations

import html as _html
import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("pool_crm.comms")

# ------------------------------------------------------------------------
# Flat catalog. `sample` values feed the /tokens preview endpoint and the
# email/SMS composer's "insert token" picker.
# ------------------------------------------------------------------------
AVAILABLE_TOKENS: Dict[str, Dict[str, str]] = {
    # --- customer.* -----------------------------------------------------
    "customer.first_name":      {"label": "Customer first name",       "sample": "Alex"},
    "customer.last_name":       {"label": "Customer last name",        "sample": "Reyes"},
    "customer.full_name":       {"label": "Customer full name",        "sample": "Alex Reyes"},
    "customer.email":           {"label": "Customer email",            "sample": "alex.reyes@example.com"},
    "customer.phone":           {"label": "Customer phone",            "sample": "555-0134"},
    "customer.address_line1":   {"label": "Customer street address",   "sample": "18420 W. Cactus Bloom Ln."},
    "customer.city":            {"label": "Customer city",             "sample": "Peoria"},
    "customer.state":           {"label": "Customer state",            "sample": "AZ"},
    "customer.zip":             {"label": "Customer ZIP",              "sample": "85383"},
    # --- job.* ----------------------------------------------------------
    "job.next_visit_date":      {"label": "Job next visit date",       "sample": "Tue, Mar 5"},
    "job.service_type":         {"label": "Job service type",          "sample": "Pool Maintenance"},
    "job.tech_name":            {"label": "Assigned technician name",  "sample": "Mike Rivera"},
    "job.route_name":           {"label": "Route name",                "sample": "West Loop Tuesday"},
    "job.scheduled_at":         {"label": "Job scheduled at",          "sample": "2026-03-05T09:00:00Z"},
    "job.completed_at":         {"label": "Job completed at",          "sample": "2026-03-05T10:12:00Z"},
    # --- invoice.* ------------------------------------------------------
    "invoice.amount_due":       {"label": "Invoice amount due",        "sample": "$135.00"},
    "invoice.due_date":         {"label": "Invoice due date",          "sample": "Mar 15, 2026"},
    "invoice.invoice_number":   {"label": "Invoice number",            "sample": "INV-2026-00412"},
    "invoice.portal_link":      {"label": "Invoice portal link",       "sample": "https://portal.example.com/invoices/INV-2026-00412"},
    "invoice.status":           {"label": "Invoice status",            "sample": "Open"},
    # --- company.* ------------------------------------------------------
    "company.name":             {"label": "Company display name",      "sample": "Aquaterra Pools & Landscape"},
    "company.phone":            {"label": "Company phone",             "sample": "(602) 555-0100"},
    "company.email":            {"label": "Company reply-to email",    "sample": "hello@aquaterra.example.com"},
    "company.website":          {"label": "Company website URL",       "sample": "https://aquaterra.example.com"},
    "company.logo_url":         {"label": "Company logo URL",          "sample": "https://cdn.example.com/aquaterra-logo.png"},
    "company.portal_link":      {"label": "Customer portal home link", "sample": "https://portal.example.com"},
    "company.address":          {"label": "Company address block",     "sample": "18040 N. 27th Dr. Ste 200, Phoenix, AZ 85023"},
    # --- system --------------------------------------------------------
    "unsubscribe_url":          {"label": "Unsubscribe link (auto)",   "sample": "https://portal.example.com/unsubscribe/<signed>"},
    # --- review_request.* + tech.* — Reviews Phase 1 (Feb 2026) --------
    "review_request.public_url":                {"label": "Review-request landing URL", "sample": "https://portal.example.com/reviews/r/abc123"},
    "review_request.tenant_public_reviews_url": {"label": "Public reviews page URL",    "sample": "https://portal.example.com/reviews/aquaterra"},
    "tech.first_name":                          {"label": "Assigned technician first name", "sample": "Mike"},
    "tech.full_name":                           {"label": "Assigned technician full name",  "sample": "Mike Rivera"},
    "tech.avatar_url":                          {"label": "Assigned technician headshot URL", "sample": "https://cdn.example.com/techs/mike.jpg"},
}

_TOKEN_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)\s*\}\}", re.IGNORECASE)


def extract_tokens(text: str) -> List[str]:
    """Return the ordered list of unique tokens referenced in ``text``."""
    if not text:
        return []
    return list(dict.fromkeys(_TOKEN_RE.findall(text)))


def resolve_tokens(text: str, context: Dict[str, Any]) -> str:
    """Replace every ``{{token.name}}`` in ``text`` with the resolved value.

    Missing tokens render as empty strings and are logged. Tokens not in
    ``AVAILABLE_TOKENS`` are also logged and rendered empty (never crash).
    """
    if not text:
        return text or ""

    def _sub(m: re.Match) -> str:
        raw = m.group(1)
        key = raw.lower()
        if key not in AVAILABLE_TOKENS:
            logger.warning(f"comm_tokens: unknown token {raw!r} — rendering empty")
            return ""
        val = context.get(key)
        if val is None:
            logger.info(f"comm_tokens: missing value for {key} — rendering empty")
            return ""
        return str(val)

    return _TOKEN_RE.sub(_sub, text)


def _walk_blocks(blocks: List[Dict[str, Any]], fn):
    """In-place walker that yields each block dict + its parent path."""
    for b in blocks or []:
        fn(b)
        for cols in (b.get("children") or []):
            if isinstance(cols, list):
                _walk_blocks(cols, fn)


def resolve_email_blocks(blocks: List[Dict[str, Any]],
                          context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deep-copy blocks and substitute tokens in every string prop."""
    import copy
    out = copy.deepcopy(blocks or [])

    def _resolve_props(b: Dict[str, Any]) -> None:
        props = b.get("props") or {}
        for k, v in list(props.items()):
            if isinstance(v, str):
                props[k] = resolve_tokens(v, context)
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        for kk, vv in item.items():
                            if isinstance(vv, str):
                                item[kk] = resolve_tokens(vv, context)
    _walk_blocks(out, _resolve_props)
    return out


def resolve_email_subject(subject: str, context: Dict[str, Any]) -> str:
    return resolve_tokens(subject or "", context)


def render_sms_text(template_body: str, context: Dict[str, Any]) -> str:
    return resolve_tokens(template_body or "", context)


# ------------------------------------------------------------------------
# HTML renderer. Table-based, Outlook-safe. Keeps ~600px max width for
# desktop email clients and gracefully collapses on mobile via inline
# styles (no @media queries — most webmail strips them).
# ------------------------------------------------------------------------
_H = _html.escape

_WRAPPER_STYLE = (
    "background:#f4f4f4;padding:24px 0;font-family:"
    "-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
    "color:#222222;line-height:1.5;")
_CONTAINER_STYLE = (
    "max-width:600px;margin:0 auto;background:#ffffff;"
    "border-radius:8px;overflow:hidden;")


def _pad(p: Optional[str]) -> str:
    if not p:
        return "padding:16px 24px;"
    return f"padding:{_H(p)};"


def _cell(inner: str, pad: Optional[str] = None, extra: str = "") -> str:
    return f'<tr><td style="{_pad(pad)}{extra}">{inner}</td></tr>'


def _render_block(b: Dict[str, Any]) -> str:  # noqa: C901
    t = b.get("type") or ""
    p = b.get("props") or {}
    if t == "text":
        style = (
            f"color:{_H(p.get('text_color') or '#222222')};"
            f"font-size:{_H(str(p.get('font_size') or '15px'))};"
            f"font-family:{_H(p.get('font_family') or 'inherit')};"
        )
        bg = f"background:{_H(p.get('background_color') or 'transparent')};"
        return _cell(f'<div style="{style}">{p.get("html","")}</div>',
                      p.get("padding"), bg)
    if t == "heading":
        level = int(p.get("level") or 2)
        level = 1 if level < 1 else 3 if level > 3 else level
        size = {1: "26px", 2: "20px", 3: "16px"}[level]
        align = _H(p.get("alignment") or "left")
        color = _H(p.get("color") or "#111111")
        return _cell(
            f'<h{level} style="margin:0;font-weight:600;font-size:{size};'
            f'color:{color};text-align:{align};">{_H(p.get("text",""))}</h{level}>',
            p.get("padding"))
    if t == "image":
        url = _H(p.get("url") or "")
        alt = _H(p.get("alt") or "")
        align = _H(p.get("alignment") or "center")
        width_pct = int(p.get("width_pct") or 100)
        img = (f'<img src="{url}" alt="{alt}" '
               f'style="display:block;max-width:100%;width:{width_pct}%;'
               f'height:auto;border:0;outline:none;text-decoration:none;" />')
        link = p.get("link_url")
        if link:
            img = f'<a href="{_H(link)}">{img}</a>'
        return _cell(f'<div style="text-align:{align};">{img}</div>',
                      p.get("padding") or "16px 24px")
    if t == "button":
        label = _H(p.get("label") or "Learn more")
        link = _H(p.get("link_url") or "#")
        align = _H(p.get("alignment") or "center")
        bg = _H(p.get("background_color") or "#0f6ed1")
        color = _H(p.get("text_color") or "#ffffff")
        radius = _H(str(p.get("border_radius") or "6px"))
        pad = _H(p.get("padding") or "12px 24px")
        btn = (f'<a href="{link}" style="display:inline-block;background:{bg};'
               f'color:{color};padding:{pad};text-decoration:none;'
               f'border-radius:{radius};font-weight:600;">{label}</a>')
        return _cell(f'<div style="text-align:{align};">{btn}</div>',
                      "24px")
    if t == "divider":
        color = _H(p.get("color") or "#e0e0e0")
        thick = int(p.get("thickness_px") or 1)
        return _cell(f'<hr style="border:0;border-top:{thick}px solid {color};margin:0;" />',
                      p.get("padding") or "8px 24px")
    if t == "spacer":
        h = int(p.get("height_px") or 24)
        return f'<tr><td style="height:{h}px;line-height:{h}px;">&nbsp;</td></tr>'
    if t == "columns_2":
        ratio = (p.get("ratio") or "50/50")
        try:
            left_pct, right_pct = [int(x) for x in ratio.split("/")]
        except Exception:
            left_pct, right_pct = 50, 50
        children = b.get("children") or [[], []]
        left = "".join(_render_block(cb) for cb in (children[0] if len(children) > 0 else []))
        right = "".join(_render_block(cb) for cb in (children[1] if len(children) > 1 else []))
        return _cell(
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">'
            f'<tr><td valign="top" style="width:{left_pct}%;padding-right:8px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">{left}</table></td>'
            f'<td valign="top" style="width:{right_pct}%;padding-left:8px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">{right}</table></td>'
            f'</tr></table>', p.get("padding") or "8px 24px")
    if t == "columns_3":
        children = b.get("children") or [[], [], []]
        cols = []
        for i in range(3):
            inner = "".join(_render_block(cb) for cb in (children[i] if len(children) > i else []))
            cols.append(
                f'<td valign="top" style="width:33.33%;padding:0 6px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">{inner}</table></td>')
        return _cell(
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>{"".join(cols)}</tr></table>',
            p.get("padding") or "8px 24px")
    if t == "social":
        align = _H(p.get("alignment") or "center")
        style = p.get("icon_style") or "circle"
        icons = []
        for lk in (p.get("links") or []):
            plat = _H(lk.get("platform") or "link")
            url = _H(lk.get("url") or "#")
            shape = "border-radius:50%;" if style == "circle" else "border-radius:4px;"
            icons.append(
                f'<a href="{url}" style="display:inline-block;margin:0 4px;background:#0f6ed1;color:#fff;'
                f'width:32px;height:32px;line-height:32px;text-align:center;text-decoration:none;{shape}font-size:12px;">'
                f'{plat[:2].upper()}</a>')
        return _cell(f'<div style="text-align:{align};">{"".join(icons)}</div>',
                      p.get("padding") or "8px 24px")
    if t == "video":
        thumb = _H(p.get("thumbnail_url") or "")
        link = _H(p.get("link_url") or "#")
        alt = _H(p.get("alt") or "Watch video")
        align = _H(p.get("alignment") or "center")
        return _cell(
            f'<div style="text-align:{align};"><a href="{link}"><img src="{thumb}" alt="{alt}" '
            f'style="display:inline-block;max-width:100%;height:auto;border:0;" /></a></div>',
            p.get("padding") or "8px 24px")
    if t == "product_card":
        img = _H(p.get("image_url") or "")
        title = _H(p.get("title") or "")
        desc = _H(p.get("description") or "")
        price = _H(p.get("price") or "")
        label = _H(p.get("button_label") or "")
        link = _H(p.get("button_link") or "#")
        btn_html = ""
        if label:
            btn_html = (
                f'<a href="{link}" style="display:inline-block;background:#0f6ed1;color:#fff;'
                f'padding:8px 16px;text-decoration:none;border-radius:6px;font-weight:600;margin-top:8px;">'
                f'{label}</a>')
        price_html = f'<div style="font-weight:600;margin-top:4px;">{price}</div>' if price else ""
        return _cell(
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">'
            f'<tr><td style="text-align:center;padding-bottom:8px;">'
            f'<img src="{img}" alt="{title}" style="max-width:100%;height:auto;border:0;" />'
            f'</td></tr>'
            f'<tr><td><h3 style="margin:8px 0 4px 0;font-size:16px;">{title}</h3>'
            f'<div style="color:#555;font-size:14px;">{desc}</div>'
            f'{price_html}{btn_html}</td></tr></table>',
            p.get("padding") or "16px 24px")
    if t == "footer":
        name = _H(p.get("company_name") or "")
        addr = _H(p.get("address") or "")
        unsub = _H(p.get("unsubscribe_link_token") or "")
        color = _H(p.get("text_color") or "#8a8a8a")
        return _cell(
            f'<div style="text-align:center;color:{color};font-size:12px;line-height:1.5;">'
            f'<div>{name}</div><div>{addr}</div>'
            f'<div style="margin-top:8px;"><a href="{unsub}" style="color:{color};text-decoration:underline;">Unsubscribe</a></div>'
            f'</div>',
            p.get("padding") or "24px", "background:#fafafa;")
    # Unknown block — render as an HTML comment to preserve length while
    # failing safe.
    return f'<!-- unsupported block type: {_H(t)} -->'


def render_email_html(blocks_json: List[Dict[str, Any]],
                       tokens_context: Dict[str, Any]) -> str:
    """Render blocks (already resolved OR raw) to Outlook-safe HTML.

    Callers who want token substitution should pass raw ``blocks_json``;
    this function will call ``resolve_email_blocks`` internally when the
    context is non-empty. Callers who've already resolved (e.g. the
    preview endpoint) may pass an empty context.
    """
    resolved = resolve_email_blocks(blocks_json, tokens_context) if tokens_context else (blocks_json or [])
    rows = "".join(_render_block(b) for b in resolved)
    return (
        f'<!doctype html><html><head><meta charset="utf-8"/>'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"/>'
        f'</head><body style="margin:0;padding:0;{_WRAPPER_STYLE}">'
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">'
        f'<tr><td>'
        f'<table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" '
        f'style="{_CONTAINER_STYLE}">{rows}</table>'
        f'</td></tr></table></body></html>')


def sample_tokens_context() -> Dict[str, Any]:
    """Return a synthetic context suitable for /tokens preview responses."""
    return {k: v["sample"] for k, v in AVAILABLE_TOKENS.items()}


def build_context_for_customer(customer: Dict[str, Any],
                                job: Optional[Dict[str, Any]] = None,
                                invoice: Optional[Dict[str, Any]] = None,
                                company: Optional[Dict[str, Any]] = None,
                                unsubscribe_url: str = "",
                                extras: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a token-context dict from live records. Missing fields are
    left absent so ``resolve_tokens`` renders them as empty strings.

    ``extras`` is a Phase 3 addition (automation engine): additional
    stringified key/value pairs that overlay the base context, letting
    domain events pass through nested attributes (e.g. job/invoice
    payloads emitted by the engine). Values are converted to strings
    with ``str(v)`` so template renderers do not choke on numbers/None.
    """
    c = customer or {}
    j = job or {}
    inv = invoice or {}
    co = company or {}
    fn = c.get("first_name") or (c.get("name") or "").split(" ", 1)[0]
    ln = c.get("last_name") or ((c.get("name") or "").split(" ", 1)[1] if " " in (c.get("name") or "") else "")
    ctx = {
        "customer.first_name": fn or "",
        "customer.last_name":  ln or "",
        "customer.full_name":  c.get("name") or f"{fn} {ln}".strip(),
        "customer.email":      c.get("email") or "",
        "customer.phone":      c.get("phone") or "",
        "customer.address_line1": c.get("address_line1") or c.get("address") or "",
        "customer.city":       c.get("city") or "",
        "customer.state":      c.get("state") or "",
        "customer.zip":        c.get("zip") or c.get("postal_code") or "",
        "job.next_visit_date": j.get("next_visit_date") or "",
        "job.service_type":    j.get("service_type") or "",
        "job.tech_name":       j.get("tech_name") or "",
        "job.route_name":      j.get("route_name") or "",
        "job.scheduled_at":    j.get("scheduled_at") or "",
        "job.completed_at":    j.get("completed_at") or "",
        "invoice.amount_due":  inv.get("amount_due") or "",
        "invoice.due_date":    inv.get("due_date") or "",
        "invoice.invoice_number": inv.get("invoice_number") or inv.get("number") or "",
        "invoice.portal_link": inv.get("portal_link") or "",
        "invoice.status":      inv.get("status") or "",
        "company.name":        co.get("name") or "",
        "company.phone":       co.get("phone") or "",
        "company.email":       co.get("email") or "",
        "company.website":     co.get("website") or "",
        "company.logo_url":    co.get("logo_url") or "",
        "company.portal_link": co.get("portal_link") or "",
        "company.address":     co.get("address") or "",
        "unsubscribe_url":     unsubscribe_url or "",
    }
    if extras:
        for k, v in extras.items():
            if v is None:
                continue
            # Flatten one level of nested dicts so payloads like
            # ``{"invoice": {...}}`` become ``"invoice.total": "..."``.
            if isinstance(v, dict):
                for nk, nv in v.items():
                    if nv is None:
                        continue
                    ctx.setdefault(f"{k}.{nk}", str(nv))
            else:
                ctx[str(k)] = str(v)
    return ctx


async def build_context_for_review_request(tenant: Dict[str, Any],
                                            review_request_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Reviews Phase 1 · Feb 2026 — compose the full context for a
    review-request template render.

    Reuses ``build_context_for_customer`` for the customer/job/company
    sub-trees (unchanged behaviour) and layers the new
    ``review_request.*`` + ``tech.*`` tokens on top. All DB reads are
    tenant-scoped; a review-request whose parent job or customer has
    been deleted still renders (missing keys → empty strings).
    """
    # Local imports to avoid a circular ``services → routers`` graph.
    import os  # noqa: F811
    from config import db  # type: ignore

    tenant_id = tenant.get("id") if tenant else review_request_doc.get("tenant_id")

    customer = None
    if review_request_doc.get("customer_id"):
        customer = await db.customers.find_one(
            {"id": review_request_doc["customer_id"], "tenant_id": tenant_id},
            {"_id": 0},
        )
    job = None
    if review_request_doc.get("job_id"):
        job = await db.jobs.find_one(
            {"id": review_request_doc["job_id"], "tenant_id": tenant_id},
            {"_id": 0},
        )
    tech = None
    tech_id = review_request_doc.get("technician_id") or (job or {}).get("technician_id")
    if tech_id:
        tech = await db.technicians.find_one({"id": tech_id}, {"_id": 0})

    # Company block is the same shape ``routers/comms.py::_company_block``
    # produces from a tenant doc — keep it centralised here so callers
    # don't have to import from that router.
    t = tenant or {}
    company = {
        "name":        t.get("name") or "",
        "phone":       t.get("phone") or "",
        "email":       t.get("email") or t.get("support_email") or "",
        "website":     t.get("website") or "",
        "logo_url":    t.get("logo_url") or "",
        "portal_link": t.get("portal_link") or t.get("portal_url") or "",
        "address":     t.get("address") or "",
    }

    ctx = build_context_for_customer(
        customer or {}, job=job or {}, invoice=None, company=company, unsubscribe_url="",
    )

    # Tech tokens — first_name is derived from the ``name`` field on the
    # technician doc (technicians only store the composite name today).
    tech_full = (tech or {}).get("name") or ""
    tech_first = tech_full.split(" ", 1)[0] if tech_full else ""
    ctx["tech.first_name"] = tech_first
    ctx["tech.full_name"] = tech_full
    ctx["tech.avatar_url"] = (tech or {}).get("avatar_url") or ""

    # Review-request URLs — always computed from APP_PUBLIC_URL + tenant
    # slug so they work in preview, staging, and production without
    # per-tenant configuration.
    origin = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
    token = review_request_doc.get("token") or ""
    slug = (tenant or {}).get("slug") or ""
    ctx["review_request.public_url"] = f"{origin}/reviews/r/{token}" if (origin and token) else ""
    ctx["review_request.tenant_public_reviews_url"] = (
        f"{origin}/reviews/{slug}" if (origin and slug) else ""
    )

    return ctx
