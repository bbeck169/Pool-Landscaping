"""Feb-2026 · UX Polish Batch B follow-up — Email preview endpoint.

Serves a "rendered-email preview" of the branded email shell for
the Business Settings page. Admin-only. NO PII: all templates use
synthetic placeholder text so the endpoint can be linked or shared
without leaking real customer/quote data.

Route:
    GET /api/tenants/me/email-preview?template=<name>

Where ``<name>`` ∈ {"quote_sent", "invoice_reminder", "password_reset",
"portal_invite"}. Any other value → 400.

Response::
    { "template": "<name>", "html": "<full wrapped HTML string>" }

Fully-wrapped HTML is produced by
:func:`services.email.theming.wrap_html_in_shell` — same helper the
production send paths call. Truthful to the actual pipeline.

See /app/memory/FEATURE_SEND_COPY_LINK_AND_EMAIL_PREVIEW.md § 2.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from utils import require_admin
from routers.tenants import get_current_tenant
from services.email.theming import wrap_html_in_shell
from services.tenants.business_settings import (
    get_effective_business_settings,
)
from services.auto_visit_email import render_email as _render_visit_email


router = APIRouter()


# ─── Stub email bodies ──────────────────────────────────────────────
# Mirror the shape of the real production builders but with fully
# synthetic placeholder text. Each returns a body FRAGMENT (no
# ``<html>``) — the shell wraps them. Kept intentionally small so
# admins get an immediate feel for the branding, not the exact
# transactional copy.

def _stub_quote_sent() -> str:
    return (
        '<div style="max-width:560px;margin:0 auto;padding:24px;'
        'font-family:-apple-system,\'Inter\',sans-serif;color:#0F172A;">'
        '<h2 style="margin:0 0 12px;">Your quote is ready</h2>'
        '<p style="margin:0 0 12px;font-size:15px;line-height:1.55;">'
        'Hi Sample Customer,</p>'
        '<p style="margin:0 0 16px;font-size:15px;line-height:1.55;">'
        'Your quote is ready to review. Click below to see the details, '
        'ask questions, or approve.</p>'
        '<p style="margin:24px 0;">'
        '<a href="#" style="display:inline-block;background:#0284C7;'
        'color:#fff;padding:12px 22px;border-radius:10px;'
        'text-decoration:none;font-weight:600;">Review quote</a></p>'
        '</div>'
    )


def _stub_invoice_reminder(locale: str = "en") -> str:
    from services.email_cta_i18n import t_email_cta
    cta_label = t_email_cta(locale, "view_invoice")
    return (
        '<div style="max-width:560px;margin:0 auto;padding:24px;'
        'font-family:-apple-system,\'Inter\',sans-serif;color:#0F172A;">'
        '<h2 style="margin:0 0 12px;">Invoice reminder</h2>'
        '<p style="margin:0 0 12px;font-size:15px;line-height:1.55;">'
        'Hi Sample Customer,</p>'
        '<p style="margin:0 0 16px;font-size:15px;line-height:1.55;">'
        'This is a friendly reminder that invoice #INV-PREVIEW '
        'has an outstanding balance of $250.00.</p>'
        '<p style="margin:24px 0;">'
        '<a href="#" style="display:inline-block;background:#DC2626;'
        'color:#fff;padding:12px 22px;border-radius:10px;'
        f'text-decoration:none;font-weight:700;font-size:22px;">{cta_label}</a></p>'
        '</div>'
    )


def _stub_password_reset() -> str:
    return (
        '<div style="max-width:560px;margin:0 auto;padding:24px;'
        'font-family:-apple-system,\'Inter\',sans-serif;color:#0F172A;">'
        '<h2 style="margin:0 0 12px;">Reset your password</h2>'
        '<p style="margin:0 0 12px;font-size:15px;line-height:1.55;">'
        'Hi Sample User,</p>'
        '<p style="margin:0 0 16px;font-size:15px;line-height:1.55;">'
        'We received a request to reset your portal password.</p>'
        '<p style="margin:24px 0;">'
        '<a href="#" style="display:inline-block;background:#0284C7;'
        'color:#fff;padding:12px 22px;border-radius:10px;'
        'text-decoration:none;font-weight:600;">Reset password</a></p>'
        '<p style="margin:0;font-size:13px;color:#475569;">'
        # Feb-2026 · hotfix — the real customer-facing reset link is
        # valid for 30 days (``_RESET_TTL_MINUTES = 43200``). The
        # preview stub was showing a stale 15-min copy; brought back
        # in sync so support screenshots of the preview match what
        # customers actually receive.
        'This link expires in 30 days.</p>'
        '</div>'
    )


def _stub_portal_invite() -> str:
    return (
        '<div style="max-width:520px;margin:0 auto;background:#ffffff;'
        'border-radius:12px;padding:28px 30px;'
        'box-shadow:0 1px 3px rgba(0,0,0,.06);color:#111827;'
        'font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif">'
        '<h1 style="margin:0 0 12px 0;font-size:20px">Password reset by admin</h1>'
        '<p style="margin:0 0 16px 0;line-height:1.55">'
        'Hi Sample User, an admin reset your password. '
        'Sign in with the temporary password below.</p>'
        '<div style="background:#f9fafb;border:1px solid #e5e7eb;'
        'border-radius:8px;padding:14px 16px;margin:0 0 20px 0">'
        '<div style="font-size:12px;color:#6b7280;text-transform:uppercase;'
        'letter-spacing:.4px;margin-bottom:4px">Temporary password</div>'
        '<div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
        'font-size:15px;font-weight:600">Preview!23</div></div>'
        '<p style="text-align:center;margin:0 0 22px 0">'
        '<a href="#" style="background:#0f766e;color:#ffffff;'
        'padding:11px 22px;border-radius:8px;text-decoration:none;'
        'font-weight:600;display:inline-block">Sign in</a></p></div>'
    )


_STUBS = {
    "quote_sent":       _stub_quote_sent,
    "invoice_reminder": _stub_invoice_reminder,
    "password_reset":   _stub_password_reset,
    "portal_invite":    _stub_portal_invite,
}


@router.get("/tenants/me/email-preview")
async def preview_email(
    template: Optional[str] = Query(
        None,
        description="One of: quote_sent, invoice_reminder, "
                    "password_reset, portal_invite. Optional "
                    "when ``preview_job_id`` is supplied — the "
                    "endpoint then renders the branded visit-"
                    "summary email regardless of ``template``.",
    ),
    locale: str = Query("en",
                        description="Preview locale: one of en/es/fr. "
                                    "Only affects invoice_reminder CTA "
                                    "label (Feb 2026 · Invoice Email "
                                    "CTA Label ticket)."),
    preview_job_id: Optional[str] = Query(
        None,
        description="Optional job id — when set, renders the branded "
                    "visit-summary email for that job (tenant-scoped). "
                    "Cross-tenant / unknown ids → 404. When omitted, "
                    "the ``template`` stub is rendered instead.",
    ),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Render the caller's branded email shell wrapping a stub body.

    Zero PII — placeholder names, invoice numbers, and passwords
    only. Truthful to production: uses the same
    ``wrap_html_in_shell`` helper the real send path calls.

    Feb-2026 · Visit-Email Preview — when ``preview_job_id`` is
    supplied, the endpoint bypasses the stub path and renders the
    real branded visit-summary email (via
    :func:`services.auto_visit_email.render_email`) against the
    caller's tenant-owned job. Cross-tenant / unknown ids return
    404. The response payload uses ``template="visit_summary"`` to
    signal the override.
    """
    if not tenant.get("id"):
        raise HTTPException(400, "Tenant context is required.")

    # Resolve branding once — both branches use it.
    try:
        branding = await get_effective_business_settings(
            db, tenant["id"], absolutize=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[email-preview] branding resolve failed: {e}")
        branding = {}

    # ─── Branded visit-summary render path (preview_job_id) ─────────
    if preview_job_id:
        job = await db.jobs.find_one(
            {"id": preview_job_id, "tenant_id": tenant["id"]},
            {"_id": 0},
        )
        if not job:
            # Covers both cross-tenant and genuinely-missing ids.
            raise HTTPException(
                404, f"Job not found: {preview_job_id!r}",
            )
        # Grab the most-recent submitted service report for this job
        # (falls back to any SR, else an empty dict). Never fails
        # the preview on SR absence — the header/pills/meta still
        # render meaningfully.
        sr = await db.service_reports.find_one(
            {"job_id": preview_job_id, "tenant_id": tenant["id"]},
            {"_id": 0},
            sort=[("submitted_at", -1)],
        ) or {}
        # Redact via the same helper the send path uses so internal
        # notes never leak into the preview.
        from routers.service_reports import _redact_report_for_customer
        safe_sr = _redact_report_for_customer(dict(sr)) if sr else {}

        customer_id = job.get("customer_id")
        customer: Dict[str, Any] = {}
        if customer_id:
            customer = await db.customers.find_one(
                {"id": customer_id, "tenant_id": tenant["id"]},
                {"_id": 0},
            ) or {}

        # Resolve the property-driven address just like the send
        # path so preview stays truthful.
        from services.auto_visit_email import (
            _resolve_visit_email_address as _resolve_addr,
        )
        resolved_address = await _resolve_addr(tenant, job)
        job_for_render = dict(job)
        if resolved_address:
            job_for_render["address"] = resolved_address

        rendered = _render_visit_email(
            tenant, job_for_render, safe_sr, customer,
            branding=branding,
        )
        return {
            "template":       "visit_summary",
            "html":           rendered["html"],
            "text":           rendered.get("text", ""),
            "subject":        rendered.get("subject", ""),
            "preview_job_id": preview_job_id,
        }

    # ─── Stub fallback path (unchanged behavior) ────────────────────
    # Feb-2026 · Batch follow-up C — when ``preview_job_id`` is
    # omitted we require ``template`` because the stubs are keyed
    # by it. When BOTH are missing, surface a clear 400 (instead
    # of the historical 422 from the required-query rejection) so
    # the caller knows either param unblocks the request.
    if not template:
        raise HTTPException(
            400,
            "Either 'template' or 'preview_job_id' is required. "
            f"Expected template ∈ {sorted(_STUBS.keys())}.",
        )
    if template not in _STUBS:
        raise HTTPException(
            400,
            f"Unknown template: {template!r}. Expected one of "
            f"{sorted(_STUBS.keys())}.",
        )
    # Feb 2026 · Invoice Email CTA Label — only the invoice_reminder
    # stub currently varies by locale; other stubs are locale-invariant
    # so we detect signature and pass only when accepted.
    stub_fn = _STUBS[template]
    try:
        body_html = stub_fn(locale)
    except TypeError:
        body_html = stub_fn()
    html = wrap_html_in_shell(body_html, branding)
    return {"template": template, "html": html}
