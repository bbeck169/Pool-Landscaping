"""Phase 4 additions:
- Portal home aggregate dashboard
- Portal invite / reset / revoke admin actions

Existing portal endpoints (`/me/*`, `/documents`, `/communications`, `/payments/checkout/{qid}`, `/setup-session`) are reused unchanged.
"""
import asyncio
import os
import secrets
import string
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from config import db, logger, APP_PUBLIC_URL
from utils import now_iso, new_id, require_admin, require_super_admin, get_current_user, hash_password
from utils import not_deleted_filter as _nd
from routers.tenants import get_current_tenant

router = APIRouter()


def _random_password(n: int = 12) -> str:
    """Generate a compliant password: >=8 chars, has upper+lower+digit."""
    alpha_lower = "abcdefghjkmnpqrstuvwxyz"
    alpha_upper = "ABCDEFGHJKMNPQRSTUVWXYZ"
    digits = "23456789"
    seed = [
        secrets.choice(alpha_upper),
        secrets.choice(alpha_lower),
        secrets.choice(digits),
    ]
    pool = alpha_upper + alpha_lower + digits
    seed += [secrets.choice(pool) for _ in range(max(1, n - 3))]
    secrets.SystemRandom().shuffle(seed)
    return "".join(seed)


# ─── Portal home aggregate ──────────────────────────────────────────────────
@router.get("/portal/home")
async def portal_home(user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    """Aggregated dashboard payload for the logged-in customer.

    Feb-2026 P0 defense-in-depth — every Mongo lookup is now scoped
    by ``tenant_id`` in addition to ``customer_id``. A misseeded
    ``users.customer_id`` cannot leak another tenant's customer/
    invoices/jobs into the response. Also emits a
    ``identity_mismatch`` flag when the JWT's ``email`` claim does
    not match the resolved customer's primary email — surfaces
    data-integrity issues immediately in the frontend without
    breaking legitimate rebinds.
    """
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Not a customer")
    cid = user["customer_id"]
    tid = tenant["id"]
    now = datetime.now(timezone.utc)
    today_iso = now.date().isoformat()

    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tid}, {"_id": 0}
    ) or {}
    # Feb-2026 P0 · JWT ↔ customer email sanity check. Log-only for
    # now (no 403) so a benign rebind doesn't lock a legitimate user
    # out; the identity_mismatch flag lets the frontend render a
    # "please re-sign-in" banner and lets ops grep the warning.
    identity_mismatch = False
    if customer and user.get("email") and customer.get("email"):
        if str(user["email"]).lower() != str(customer["email"]).lower():
            identity_mismatch = True
            logger.warning(
                "[portal_home] JWT identity mismatch — "
                "user_id=%s user_email=%s customer_id=%s customer_email=%s tenant=%s",
                user.get("id"), user.get("email"),
                customer.get("id"), customer.get("email"), tid,
            )
    jobs = await db.jobs.find(
        {"customer_id": cid, "tenant_id": tid}, {"_id": 0}
    ).sort("scheduled_date", 1).to_list(200)

    upcoming = [
        j for j in jobs
        if (j.get("status") in ("scheduled", "active", "pending", "requested"))
        and (not j.get("scheduled_date") or str(j["scheduled_date"])[:10] >= today_iso)
    ]
    past = [
        j for j in jobs
        if j.get("status") in ("completed", "cancelled") or (j.get("scheduled_date") and str(j["scheduled_date"])[:10] < today_iso)
    ]
    past.sort(key=lambda j: j.get("completed_at") or j.get("scheduled_date") or "", reverse=True)

    invs = await db.quotes.find(
        {"customer_id": cid, "tenant_id": tid, "doc_type": "invoice"}, {"_id": 0}
    ).to_list(500)
    overdue_count = 0
    outstanding = 0.0
    for i in invs:
        remaining = max(0.0, float(i.get("total") or 0) - float(i.get("amount_paid") or 0))
        outstanding += remaining
        if remaining > 0 and i.get("due_date") and str(i["due_date"])[:10] < today_iso:
            overdue_count += 1

    estimates = await db.quotes.find(
        {"customer_id": cid, "tenant_id": tid, "doc_type": "quote"}, {"_id": 0}
    ).to_list(500)
    pending_estimates = [
        e for e in estimates
        if e.get("status") in ("sent", "draft") and e.get("decision") not in ("approved", "declined")
    ]

    unread_msgs = 0
    try:
        threads = await db.communications.find(
            {"customer_id": cid, "tenant_id": tid}, {"messages": 1, "_id": 0}
        ).to_list(200)
        for t in threads:
            for m in (t.get("messages") or []):
                if not m.get("read_by_customer") and m.get("from_role") in ("admin", "technician", "assistant"):
                    unread_msgs += 1
    except Exception:
        pass

    return {
        "customer": customer,
        "next_visit": upcoming[0] if upcoming else None,
        "last_visit": past[0] if past else None,
        "counts": {
            "upcoming_jobs": len(upcoming),
            "overdue_invoices": overdue_count,
            "outstanding_total": round(outstanding, 2),
            "pending_estimates": len(pending_estimates),
            "unread_messages": unread_msgs,
        },
        # Feb-2026 P0 · surface the JWT ↔ customer email mismatch to
        # the frontend so a stale prod session (or a mis-linked
        # ``users.customer_id``) is immediately visible.
        "identity_mismatch": identity_mismatch,
    }


# ─── Portal invite / reset / revoke ────────────────────────────────────────
class PortalInviteResp(BaseModel):
    ok: bool = True
    email: str
    login_url: str
    password: Optional[str] = None
    emailed: bool = False


async def _upsert_customer_user(cid: str, tenant_id: str, email: str, password: str) -> None:
    # Feb-2026 · Customer temp password + first-access tracking —
    # every admin-provisioned password is a TEMP password. Set the
    # ``must_change_password_on_next_login`` flag so the login flow
    # forks into ``password_reset_required`` on the customer's next
    # sign-in. The flag is cleared inside ``_apply_new_password``
    # (see ``auth.py``) so the reset consummation flip is idempotent.
    hashed = hash_password(password)
    existing = await db.users.find_one({"customer_id": cid, "tenant_id": tenant_id}, {"_id": 0})
    if existing:
        await db.users.update_one(
            {"id": existing["id"]},
            {"$set": {
                "password_hash": hashed,
                "email": email.lower(),
                "active": True,
                "must_change_password_on_next_login": True,
                "temp_password_issued_at": now_iso(),
            }},
        )
    else:
        await db.users.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "name": (await db.customers.find_one({"id": cid, "tenant_id": tenant_id}) or {}).get("name", ""),
            "email": email.lower(),
            "password_hash": hashed,
            "role": "customer",
            "avatar": "",
            "technician_id": None,
            "customer_id": cid,
            "active": True,
            "created_at": now_iso(),
            "must_change_password_on_next_login": True,
            "temp_password_issued_at": now_iso(),
            "has_ever_logged_in": False,
            "first_access_at": None,
        })
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant_id}, {"$set": {"email": email.lower(), "has_login": True}}
    )


# ══════════════════════════════════════════════════════════════════
# TE-portal-job · Feb-2026 — module-level hardcoded fallback
# constants for the portal-invite email.
#
# Feb-2026 · Portal-invite merge-tags fix — placeholders switched
# from single-brace ``{name}`` / ``{to}`` / ``{temp_password}`` /
# ``{login_url}`` to double-brace ``{{NAME}}`` / ``{{TO}}`` /
# ``{{TEMP_PASSWORD}}`` / ``{{LOGIN_URL}}`` so the same
# ``services.marketing.merge_tags.render_template`` pass that
# resolves catalog tags (``{{COMPANY_NAME}}`` / ``{{COMPANY_PHONE}}``)
# also resolves the local value tokens.  ``str.format(...)`` is
# gone — see ``_try_send_reset_email``.
#
# Used when the tenant has no row in ``marketing_templates`` for
# ``code=portal_invite_email`` OR when the DB read fails / the
# caller omits ``tenant_id``.
#
# ANY EDIT HERE MUST BE MIRRORED in
# ``migrations/te_portal_job_templates_seed.py`` so the DB seed and
# the fallback never drift.
# ══════════════════════════════════════════════════════════════════
_HARDCODED_INVITE_SUBJECT = "Your customer portal login"
_HARDCODED_INVITE_HTML_TPL = (
    "<p>Hi {{NAME}},</p>"
    "<p>Your portal login is ready.</p>"
    "<p><strong>Email:</strong> {{TO}}</p>"
    "<p><strong>Temporary password:</strong> "
    "<code>{{TEMP_PASSWORD}}</code></p>"
    "<p><a href='{{LOGIN_URL}}'>Sign in here</a> and change "
    "your password from Profile.</p>"
)
_HARDCODED_INVITE_TEXT_TPL = (
    "Hi {{NAME}},\n\n"
    "Your portal login is ready.\n\n"
    "Email: {{TO}}\n"
    "Temporary password: {{TEMP_PASSWORD}}\n\n"
    "Sign in here: {{LOGIN_URL}}\n"
    "and change your password from Profile."
)


async def _try_send_reset_email(
    to: str,
    name: str,
    temp_password: str,
    login_url: str,
    tenant_id: Optional[str] = None,
) -> Optional[str]:
    """Send the reset email. Returns the Resend ``email_id`` on success
    (a non-empty string), or ``None`` when the send failed or the API
    key isn't configured. Callers historically treated the return as
    a bool ("did it send?") — that idiom still works because a
    non-empty string is truthy and ``None`` is falsy.

    Phase P34 · Feb-2026 — surfaced the Resend response id so the
    outbox row + webhook events can be correlated per-send.

    TE-portal-job · Feb-2026 — 3-tier body fallback:
        1. Tenant's ``marketing_templates`` row (``code=
           portal_invite_email``) — either the ``is_system=True``
           seed default OR a user-edited override — resolved via
           ``services.marketing_template_lookup.get_template_by_code``.
        2. Module-level hardcoded constants
           (``_HARDCODED_INVITE_SUBJECT`` / ``_HARDCODED_INVITE_HTML_TPL``
           / ``_HARDCODED_INVITE_TEXT_TPL``) — reached when
           ``tenant_id`` is None, the row is missing/inactive, or
           the DB lookup raises.

    The plain-text alternative body always uses the hardcoded text
    template — the DB row only carries the HTML variant, and the
    text-only fallback path is a rare secondary render used by
    HTML-averse clients.

    Feb-2026 · Portal-invite merge-tags fix
    ────────────────────────────────────────
    Rendering is now handled by
    ``services.marketing.merge_tags.render_template(body, ctx,
    missing='empty')`` instead of the fragile ``str.format(**kw)``
    (which silently ignored missing keys and rendered
    ``{{COMPANY_NAME}}`` as a literal ``{COMPANY_NAME}`` after brace
    de-doubling).  The tenant record is fetched from Mongo and
    injected into ``ctx`` so the catalog resolvers for
    ``{{COMPANY_NAME}}`` / ``{{COMPANY_PHONE}}`` /
    ``{{COMPANY_EMAIL}}`` etc. hit their preferred
    ``settings.business_card`` source of truth.

    Pre-send safety rail — INTENTIONAL DIVERGENCE from other send
    paths (``referral_watcher``, ``equipment_trackers_cron``, etc.)
    which pass ``missing='empty'`` and let missing tokens render as
    blank strings. Portal invites carry more customer-trust weight
    than the periodic notification paths, so a first-touch email
    with a blank company name / phone is aborted in favor of a
    delayed retry. Company-name AND company-phone resolvers each
    cascade through
    ``settings.business_card`` → legacy tenant fields → per-slug
    ``_BUSINESS_CARD_DEFAULTS`` so the abort ONLY fires on genuinely
    broken tenant data. Compatible with P34's ``Optional[str]``
    contract — abort returns ``None`` and the caller treats it as a
    send failure (a retry re-fires the branding check on the fresh
    tenant record).
    """
    from config import RESEND_API_KEY, EMAIL_FROM
    if not RESEND_API_KEY:
        return None
    # TE-portal-job · Feb-2026 — Tier 1 · try the tenant's DB row.
    subject = _HARDCODED_INVITE_SUBJECT
    body_tpl = _HARDCODED_INVITE_HTML_TPL
    text_tpl = _HARDCODED_INVITE_TEXT_TPL
    tenant_record: dict = {}
    if tenant_id:
        try:
            from services.marketing_template_lookup import (
                get_template_by_code,
            )
            tpl = await get_template_by_code(
                "portal_invite_email", tenant_id,
            )
            if tpl and tpl.get("body"):
                body_tpl = tpl["body"]
                if tpl.get("subject"):
                    subject = tpl["subject"]
        except Exception as _exc:
            logger.warning(
                "[te-portal-job] portal_invite_email DB lookup "
                "failed for tenant=%s: %s", tenant_id, _exc,
            )
        # Fetch the tenant record so the ``{{COMPANY_*}}`` catalog
        # resolvers reach the source-of-truth ``settings.business_card``
        # data.  Best-effort — a Mongo hiccup logs a warning and
        # falls through to an empty tenant dict; the pre-send
        # branding check below will then abort the send.
        try:
            tenant_record = await db.tenants.find_one(
                {"id": tenant_id}, {"_id": 0},
            ) or {}
        except Exception as _exc:
            logger.warning(
                "[portal-invite] tenant record lookup failed for "
                "tenant=%s: %s", tenant_id, _exc,
            )
            tenant_record = {}

    # Build the render context.  Flat keys resolve at cascade level
    # 1 in ``render_template``; ``tenant`` is nested so the catalog
    # ``_company_name`` / ``_company_phone`` resolvers can walk
    # ``ctx['tenant']['settings']['business_card']``.
    ctx: dict = {
        "name": name or "",
        "to": to,
        "temp_password": temp_password,
        "login_url": login_url,
        "tenant": tenant_record,
    }

    # Pre-send safety rail — verify company_name AND company_phone
    # resolve to non-empty strings.  See the docstring for the
    # rationale (intentional divergence from the other send paths).
    from services.marketing.merge_tags import (
        render_template,
        rebrace_single_brace_catalog_tokens,
        normalize_url_encoded_merge_tags,
        _company_name as _resolve_company_name,
        _company_phone as _resolve_company_phone,
    )
    company_name = _resolve_company_name(ctx)
    company_phone = _resolve_company_phone(ctx)
    if not company_name or not company_phone:
        logger.warning(
            "[portal-invite] aborting send for %s — missing tenant"
            " branding (company_name=%r, company_phone=%r,"
            " tenant_id=%s). Fix the tenant's Business Card"
            " settings and retry.",
            to, company_name, company_phone, tenant_id,
        )
        return None

    # Phase 21 · Feb-2026 — URL-encoded merge-tag repair. Some
    # tenants have portal-invite bodies stored with URL-encoded
    # brace sequences (``%7B%7BNAME%7D%7D`` et al.) — stems from
    # rich-text clipboard-paste paths, legacy querystring
    # migrations, or an operator pasting an already-encoded
    # sample as the template default. The ``render_template``
    # regex only matches literal ``{{…}}`` so the encoded tokens
    # slipped through to the recipient. Normalise BEFORE the
    # single-brace catalog upgrade so both encodings fold back
    # to a single canonical shape in one pre-render pass.
    subject = normalize_url_encoded_merge_tags(subject)
    body_tpl = normalize_url_encoded_merge_tags(body_tpl)
    text_tpl = normalize_url_encoded_merge_tags(text_tpl)

    # Feb-2026 · Portal-invite merge-tag fix — legacy / user-edited
    # DB rows sometimes carry catalog tokens in the single-brace
    # form (``{COMPANY_NAME}``) which the double-brace-only
    # ``render_template`` regex ignores.  Upgrade every recognised
    # catalog token to its canonical double-brace form BEFORE the
    # render pass so ``{COMPANY_NAME}`` / ``{COMPANY_PHONE}`` /
    # ``{CUSTOMER_FULL_NAME}`` / ``{CUSTOMER_PORTAL_LINK}`` / etc.
    # all resolve.  Non-catalog braces (``{2024}`` etc.) are left
    # byte-identical.  Scoped to this send path per the fix brief.
    subject = rebrace_single_brace_catalog_tokens(subject)
    body_tpl = rebrace_single_brace_catalog_tokens(body_tpl)
    text_tpl = rebrace_single_brace_catalog_tokens(text_tpl)

    # M-TAG-FIX · Feb-2026 — empty-TEMP_PASSWORD paragraph strip.
    # When no temporary password is minted (e.g. re-sending a login
    # reminder on an already-active portal account), the enclosing
    # ``<p>…{{TEMP_PASSWORD}}…</p>`` line is removed from both the
    # HTML and plain-text surfaces BEFORE substitution so the
    # recipient never sees a dangling "Temporary password: " prefix.
    # The template authoring contract is that ``{{TEMP_PASSWORD}}``
    # lives on its own line/paragraph for this strip to work
    # correctly — enforced for the hardcoded fallback above.
    if not (temp_password or "").strip():
        import re as _re
        body_tpl = _re.sub(
            r"<p[^>]*>(?:(?!</?p\b)[\s\S])*?"
            r"\{\{\s*TEMP_PASSWORD\s*\}\}"
            r"(?:(?!</?p\b)[\s\S])*?</p>",
            "",
            body_tpl,
            flags=_re.IGNORECASE,
        )
        text_tpl = _re.sub(
            r"^.*\{\{\s*TEMP_PASSWORD\s*\}\}.*\r?\n?",
            "",
            text_tpl,
            flags=_re.IGNORECASE | _re.MULTILINE,
        )

    # Render the three surfaces through the same engine so a token
    # that appears in only one surface still resolves uniformly.
    subject_rendered, _ = render_template(subject, ctx, missing="empty")
    inner_html, _ = render_template(body_tpl, ctx, missing="empty")
    text_body, _ = render_template(text_tpl, ctx, missing="empty")

    try:
        import resend
        resend.api_key = RESEND_API_KEY
        # Phase P34 · Feb-2026 — wrap the reset-email inner HTML in
        # the shared brand shell so the customer sees the same
        # logo + header treatment used on invoice + estimate
        # emails. ``wrap_html_in_shell`` accepts a body fragment
        # only (NOT a full document) and returns a full
        # ``<!doctype html>...`` shell around it.
        from services.email.theming import wrap_html_in_shell
        wrapped_html = wrap_html_in_shell(inner_html, branding=None)
        # safe-send: allowlist because legacy direct SDK call is gated by sdk_intercept.install_resend_gate() at the Resend SDK boundary; SAFE-SEND-D full migration pending
        resp = resend.Emails.send({
            "from": EMAIL_FROM or "onboarding@resend.dev",
            "to": [to],
            "subject": subject_rendered,
            "html": wrapped_html,
            "text": text_body,
        })
        # Resend SDK returns a dict-shaped response: ``{"id": "..."}``.
        # If the shape is unexpected we still report a truthy sentinel
        # so callers don't downgrade a successful send to a failure.
        if isinstance(resp, dict):
            return str(resp.get("id") or "resend-unknown-id")
        return "resend-unknown-id"
    except Exception as e:
        logger.warning(f"Portal invite email failed: {e}")
        return None


async def _record_portal_invite_outbox(
    *,
    email_id: str,
    tenant_id: str,
    customer_id: str,
    recipient: str,
) -> None:
    """Phase P34 · Feb-2026 — insert (or refresh) an ``email_outbox``
    row correlating a portal-invite send to Resend's email id. The
    row is kept in lockstep with ``resend_webhook_events`` via the
    ``email_id`` foreign key; downstream ``latest_status`` /
    ``latest_status_ts`` updates land inside the webhook handler.

    Best-effort — DB errors are logged and swallowed so a persistence
    failure never blocks the invite send itself."""
    if not email_id:
        return
    try:
        await db.email_outbox.update_one(
            {"email_id": email_id},
            {"$set": {
                "email_id": email_id,
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "kind": "portal_invite",
                "recipient": (recipient or "").strip().lower(),
                "latest_status": "sent",
                "latest_status_ts": now_iso(),
                "updated_at": now_iso(),
            },
             "$setOnInsert": {
                "id": new_id(),
                "created_at": now_iso(),
            }},
            upsert=True,
        )
    except Exception as _e:  # noqa: BLE001
        logger.warning(
            f"[phase-p34] email_outbox upsert failed for {email_id}: {_e}",
        )


@router.post("/customers/{cid}/portal-invite", response_model=PortalInviteResp)
async def portal_invite(cid: str, user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    """Provisions the customer's portal login with an auto-generated password.
    Emails it via Resend if configured; otherwise returns the password in-body
    so the admin can send it manually."""
    return await _do_portal_provision(cid, tenant["id"], user, explicit_password=None)


class PortalResetBody(BaseModel):
    password: Optional[str] = None


@router.post("/customers/{cid}/portal-reset", response_model=PortalInviteResp)
async def portal_reset(
    cid: str,
    body: Optional[PortalResetBody] = None,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Rotates the customer's portal password.
    If `password` is provided in body, sets it explicitly (validated against
    the standard password policy). Otherwise generates a random one."""
    explicit = (body.password if body else None) or None
    return await _do_portal_provision(cid, tenant["id"], user, explicit_password=explicit)


async def _do_portal_provision(cid: str, tenant_id: str, actor: dict,
                                 explicit_password: Optional[str]) -> PortalInviteResp:
    from models import validate_password_strength
    # SEC-002 hotfix: tenant-scoped customer lookup. Cross-tenant CID → 404.
    cust = await db.customers.find_one({"id": cid, "tenant_id": tenant_id}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Customer not found")
    email = (cust.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Customer has no email on file")

    if explicit_password:
        try:
            validate_password_strength(explicit_password)
        except ValueError as e:
            raise HTTPException(400, str(e))
        password = explicit_password
    else:
        password = _random_password()

    await _upsert_customer_user(cid, tenant_id, email, password)
    # Audit-log the portal-reset action for accountability.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "event": "portal_reset",
            "actor_id": (actor or {}).get("id"),
            "actor_email": (actor or {}).get("email"),
            "target_customer_id": cid,
            "target_email": email,
            "created_at": now_iso(),
        })
    except Exception:
        pass
    login_url = f"{APP_PUBLIC_URL or ''}/login"
    emailed = False
    email_id: Optional[str] = None
    if not explicit_password:
        email_id = await _try_send_reset_email(
            email, cust.get("name", ""), password, login_url,
            tenant_id=tenant_id,
        )
        emailed = bool(email_id)
        # Phase P34 · Feb-2026 — persist an outbox correlation row so
        # the admin delivery-status polling endpoint + Resend webhook
        # can trace each portal-invite send end-to-end.
        if email_id:
            await _record_portal_invite_outbox(
                email_id=email_id,
                tenant_id=tenant_id,
                customer_id=cid,
                recipient=email,
            )
    return PortalInviteResp(
        email=email,
        login_url=login_url,
        password=password if not emailed else None,
        emailed=emailed,
    )


# ─── K30 · Feb-2026 · Admin-triggered tokenized password-reset link ────
#
# Sits alongside ``/customers/{cid}/portal-reset`` (which emails a
# temp password) — this endpoint emits a SINGLE-USE opaque token
# link into ``password_reset_tokens`` (30-min TTL, matches the
# ``/auth/forgot-password`` self-serve flow) so the customer never
# sees a raw password over email. Admin-only, tenant-scoped, and
# uses the ``allow_off_allowlist=True`` bypass on the resend
# adapter because admin-driven support actions must land in the
# customer's inbox even from preview environments.

class PortalResetLinkResp(BaseModel):
    ok: bool = True
    sent_to: str
    # Feb-2026 · hotfix — bumped from 30 (minutes) to 43200 (30 days)
    # to track the widened ``_RESET_TTL_MINUTES``.  Field unit is
    # still MINUTES (keeps the name honest and existing frontend
    # consumers that divide by 60 or format via a shared helper
    # continue to work).
    token_ttl_minutes: int = 43200
    provisioned_user: bool = False


def _mask_email_for_response(email: str) -> str:
    """Return ``t***@example.com`` shape so audit/UI never echoes the
    full address back through the admin response body."""
    if not email or "@" not in email:
        return email or ""
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


@router.post("/customers/{cid}/portal-reset-link", response_model=PortalResetLinkResp)
async def portal_reset_link(cid: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    """K30 · Feb-2026 — Admin-triggered password-reset LINK.

    Distinct from the pre-existing ``/portal-reset`` (temp password)
    and ``/portal-invite`` (temp password) endpoints. Behaviour:

    1. Tenant-scoped customer lookup — ``deleted_at`` is permitted
       (per K30 policy Q2 the reset link may still be issued for a
       soft-deleted customer, though login itself will remain
       gated by ``routers.auth.login`` until the customer is
       restored — see ``/customers/{cid}/restore``).
    2. Auto-provision a ``role="customer"`` ``users`` row if one is
       missing, reusing ``_upsert_customer_user`` with a random
       throwaway password (the customer never learns it — they set
       their own via the reset link).
    3. Mint an opaque single-use token in ``password_reset_tokens``
       (30-min TTL, invalidate prior unused tokens for the same
       user — mirrors the ``/auth/forgot-password`` contract).
    4. Send the reset-link email via the guarded Resend adapter with
       ``allow_off_allowlist=True`` so admin-triggered support
       actions leave preview environments.
    5. Audit event ``admin_password_reset_triggered`` on
       ``db.audit_logs`` with actor id + email, target customer id,
       tenant id, masked recipient, and adapter outcome.

    Response: ``{ok, sent_to (masked), token_ttl_minutes: 43200,
    provisioned_user: bool}``. Never leaks the full recipient email
    or the token itself to the caller.
    """
    from routers.auth import _password_reset_email_html

    tid = tenant["id"]
    cust = await db.customers.find_one({"id": cid, "tenant_id": tid}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Customer not found")

    email = (cust.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Customer has no email on file")

    # Auto-provision the portal user row if missing.
    existing = await db.users.find_one(
        {"customer_id": cid, "tenant_id": tid, "role": "customer"},
        {"_id": 0, "id": 1, "email": 1},
    )
    provisioned_user = False
    if not existing:
        await _upsert_customer_user(cid, tid, email, _random_password(16))
        existing = await db.users.find_one(
            {"customer_id": cid, "tenant_id": tid, "role": "customer"},
            {"_id": 0, "id": 1, "email": 1},
        )
        provisioned_user = True

    if not existing:
        # Provisioning must have succeeded above; defensive guard.
        raise HTTPException(500, "Failed to provision portal user")

    # Mint the reset token — mirrors auth.forgot_password shape 1:1.
    from datetime import datetime, timezone, timedelta
    from routers.auth import _RESET_TTL_MINUTES

    await db.password_reset_tokens.update_many(
        {"user_id": existing["id"], "used_at": None},
        {"$set": {"invalidated_at": now_iso()}},
    )
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_RESET_TTL_MINUTES)
    await db.password_reset_tokens.insert_one({
        "id": new_id(),
        "token": token,
        "user_id": existing["id"],
        "tenant_id": tid,
        "email": email,
        "expires_at": expires_at.isoformat(),
        "used_at": None,
        "invalidated_at": None,
        "created_at": now_iso(),
        "created_ip": None,
        "source": "admin_reset_link",
        "actor_user_id": (user or {}).get("id"),
    })

    frontend_url = (APP_PUBLIC_URL or os.environ.get("FRONTEND_URL") or "").rstrip("/")
    reset_link = f"{frontend_url}/reset-password?token={token}"

    first_name = (
        cust.get("first_name")
        or (cust.get("name") or "").split(" ")[0]
        or "there"
    )
    html = _password_reset_email_html(
        first_name=first_name,
        reset_link=reset_link,
        expiry_minutes=_RESET_TTL_MINUTES,
    )

    send_outcome: dict = {"provider_status": "not_attempted"}
    try:
        from services.email.resend_adapter import send as _send_email
        send_outcome = await _send_email(
            to=email,
            subject="Reset your password",
            html=html,
            category="transactional",
            tenant_id=tid,
            customer_id=cid,
            allow_off_allowlist=True,
        )
        logger.info(
            "[k30] admin_password_reset_triggered actor=%s cid=%s status=%s attempts=%s",
            (user or {}).get("email"), cid,
            send_outcome.get("provider_status"),
            send_outcome.get("attempts"),
        )
    except Exception as exc:  # pragma: no cover — belt-and-braces
        logger.warning("[k30] admin reset link send failed: %s", exc)
        send_outcome = {"provider_status": "failed",
                         "error": f"{type(exc).__name__}: {exc}"}

    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tid,
            "event": "admin_password_reset_triggered",
            "actor_id": (user or {}).get("id"),
            "actor_email": (user or {}).get("email"),
            "target_customer_id": cid,
            "target_email_masked": _mask_email_for_response(email),
            "provisioned_user": provisioned_user,
            "provider_status": send_outcome.get("provider_status"),
            "provider_attempts": send_outcome.get("attempts"),
            "customer_soft_deleted": bool(cust.get("deleted_at")),
            "created_at": now_iso(),
        })
    except Exception:  # pragma: no cover
        logger.warning("[k30] audit_logs insert failed")

    return PortalResetLinkResp(
        sent_to=_mask_email_for_response(email),
        token_ttl_minutes=_RESET_TTL_MINUTES,
        provisioned_user=provisioned_user,
    )


# ─── K30.copy-admin-link · Feb-2026 · Super-admin clipboard-copy ──────
#
# Companion endpoint to ``portal_reset_link`` above. Same token
# minting semantics (30-min TTL, prior tokens invalidated,
# ``source="admin_reset_link_copy"``, portal user auto-provisioned)
# but the *email is never sent* and the response body returns the
# fully-qualified reset URL so a super-admin on the phone with the
# customer can paste it directly into a text message / SMS / live
# chat channel.
#
# Rationale for the stricter super_admin gate (vs the send path's
# admin gate): the response body carries the token — a bearer
# credential — in plaintext. Restricting to super_admin keeps the
# blast radius narrow and matches how "impersonate" is gated.

class PortalResetLinkCopyResp(BaseModel):
    ok: bool = True
    reset_url: str
    expires_at: str
    # Feb-2026 · hotfix — matches ``_RESET_TTL_MINUTES``. Unit is
    # still minutes; see ``PortalResetLinkResp`` for rationale.
    token_ttl_minutes: int = 43200
    provisioned_user: bool = False


@router.post("/customers/{cid}/portal-reset-link-copy",
              response_model=PortalResetLinkCopyResp)
async def portal_reset_link_copy(cid: str,
                                    user: dict = Depends(require_super_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    """K30.copy-admin-link · Feb-2026 — Mint a fresh reset URL for a
    customer and return it directly to the super-admin caller so it
    can be copied to clipboard (never emailed on this path).

    Behavioural parity with ``portal_reset_link`` for token
    minting:

    1. Tenant-scoped customer lookup (``deleted_at`` permitted,
       same policy as the send path).
    2. Auto-provision the ``role="customer"`` ``users`` row when
       missing.
    3. Invalidate prior unused tokens for the same user before
       minting the new one.
    4. New token row carries ``source="admin_reset_link_copy"`` so
       audits can distinguish the copy path from the email path.

    Deviations from the send path:

    * ``require_super_admin`` (send path allows admin).
    * NO email adapter call. Adapter code path is untouched.
    * Response body includes the FULL ``reset_url`` and
       ``expires_at``. The token value only appears here; it is
       never logged.
    * Audit event key is ``admin_password_reset_copied`` (send
       path uses ``admin_password_reset_triggered``).
    """
    from datetime import datetime, timezone, timedelta
    from routers.auth import _RESET_TTL_MINUTES

    tid = tenant["id"]
    cust = await db.customers.find_one({"id": cid, "tenant_id": tid}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Customer not found")

    email = (cust.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Customer has no email on file")

    existing = await db.users.find_one(
        {"customer_id": cid, "tenant_id": tid, "role": "customer"},
        {"_id": 0, "id": 1, "email": 1},
    )
    provisioned_user = False
    if not existing:
        await _upsert_customer_user(cid, tid, email, _random_password(16))
        existing = await db.users.find_one(
            {"customer_id": cid, "tenant_id": tid, "role": "customer"},
            {"_id": 0, "id": 1, "email": 1},
        )
        provisioned_user = True

    if not existing:  # pragma: no cover — defensive
        raise HTTPException(500, "Failed to provision portal user")

    await db.password_reset_tokens.update_many(
        {"user_id": existing["id"], "used_at": None},
        {"$set": {"invalidated_at": now_iso()}},
    )
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_RESET_TTL_MINUTES)
    await db.password_reset_tokens.insert_one({
        "id": new_id(),
        "token": token,
        "user_id": existing["id"],
        "tenant_id": tid,
        "email": email,
        "expires_at": expires_at.isoformat(),
        "used_at": None,
        "invalidated_at": None,
        "created_at": now_iso(),
        "created_ip": None,
        "source": "admin_reset_link_copy",
        "actor_user_id": (user or {}).get("id"),
    })

    frontend_url = (APP_PUBLIC_URL or os.environ.get("FRONTEND_URL") or "").rstrip("/")
    reset_url = f"{frontend_url}/reset-password?token={token}"

    # IMPORTANT — never log the token value. Log only the audit
    # metadata + masked recipient. The URL itself is returned to
    # the caller (super-admin) only.
    logger.info(
        "[k30.copy] admin_password_reset_copied actor=%s cid=%s masked_to=%s provisioned=%s",
        (user or {}).get("email"),
        cid,
        _mask_email_for_response(email),
        provisioned_user,
    )

    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tid,
            "event": "admin_password_reset_copied",
            "actor_id": (user or {}).get("id"),
            "actor_email": (user or {}).get("email"),
            "target_customer_id": cid,
            "target_email_masked": _mask_email_for_response(email),
            "provisioned_user": provisioned_user,
            "customer_soft_deleted": bool(cust.get("deleted_at")),
            "created_at": now_iso(),
        })
    except Exception:  # pragma: no cover
        logger.warning("[k30.copy] audit_logs insert failed")

    return PortalResetLinkCopyResp(
        reset_url=reset_url,
        expires_at=expires_at.isoformat(),
        token_ttl_minutes=_RESET_TTL_MINUTES,
        provisioned_user=provisioned_user,
    )


# ─── K30.status-chip · Feb-2026 · latest reset-link status ─────────────
#
# Lightweight read endpoint powering the "Reset link" chip on the
# Portal Access panel. Reads only the LATEST row in
# ``password_reset_tokens`` for the customer's linked ``users`` row
# and classifies it into one of four states. Never returns the
# token value itself — the chip is purely a UX signal for the
# front-office ("did the customer click it yet?").

class PortalResetLinkStatusResp(BaseModel):
    status: str  # "none" | "issued" | "used" | "expired"
    issued_at: Optional[str] = None
    used_at: Optional[str] = None
    expires_at: Optional[str] = None
    source: Optional[str] = None  # "admin_reset_link" | "forgot_password" | None


@router.get("/customers/{cid}/portal-reset-link-status",
            response_model=PortalResetLinkStatusResp)
async def portal_reset_link_status(cid: str,
                                     user: dict = Depends(require_admin),
                                     tenant: dict = Depends(get_current_tenant)):
    """K30.status-chip · Feb-2026 — Return the state of the LATEST
    ``password_reset_tokens`` row for this customer's portal user.

    Contract:

    * ``none``     — no reset token has ever been minted for this
                      customer's user row (or no user row exists).
    * ``issued``   — a token exists, ``used_at`` is null, and
                      ``expires_at`` is in the future.
    * ``used``     — the latest token has ``used_at`` set (customer
                      completed the reset).
    * ``expired``  — the latest token has ``used_at`` null AND
                      ``expires_at`` is in the past (or the row
                      carries ``invalidated_at`` and no newer token
                      exists).

    Never returns the raw ``token`` — the chip is metadata only.
    """
    from datetime import datetime, timezone

    if not await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
    ):
        raise HTTPException(404, "Customer not found")

    cust_user = await db.users.find_one(
        {"customer_id": cid, "tenant_id": tenant["id"], "role": "customer"},
        {"_id": 0, "id": 1},
    )
    if not cust_user:
        return PortalResetLinkStatusResp(status="none")

    row = await db.password_reset_tokens.find_one(
        {"user_id": cust_user["id"], "tenant_id": tenant["id"]},
        {"_id": 0, "token": 0},  # NEVER return the token value
        sort=[("created_at", -1)],
    )
    if not row:
        return PortalResetLinkStatusResp(status="none")

    if row.get("used_at"):
        return PortalResetLinkStatusResp(
            status="used",
            issued_at=row.get("created_at"),
            used_at=row.get("used_at"),
            expires_at=row.get("expires_at"),
            source=row.get("source"),
        )

    # Not used — decide between issued and expired.
    exp_raw = row.get("expires_at")
    is_expired = bool(row.get("invalidated_at"))
    if not is_expired and exp_raw:
        try:
            exp_dt = (exp_raw if isinstance(exp_raw, datetime)
                       else datetime.fromisoformat(exp_raw))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            is_expired = exp_dt < datetime.now(timezone.utc)
        except Exception:  # pragma: no cover — fail closed as expired
            is_expired = True

    return PortalResetLinkStatusResp(
        status="expired" if is_expired else "issued",
        issued_at=row.get("created_at"),
        expires_at=row.get("expires_at"),
        source=row.get("source"),
    )


@router.post("/customers/{cid}/portal-revoke")
async def portal_revoke(cid: str, user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    """Deactivates the customer's portal login. SEC-002 hotfix: tenant-scoped."""
    res = await db.users.update_many(
        {"customer_id": cid, "tenant_id": tenant["id"], "role": "customer"},
        {"$set": {"active": False, "revoked_at": now_iso()}},
    )
    await db.customers.update_one({"id": cid, "tenant_id": tenant["id"]},
                                    {"$set": {"has_login": False}})
    # Feb-2026 Portal Access ship — audit trail for revocations too.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "event": "portal_revoke",
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "target_customer_id": cid,
            "created_at": now_iso(),
        })
    except Exception:
        pass
    return {"ok": True, "revoked": res.modified_count}


# ─── Feb-2026 Portal Access ship ──────────────────────────────────────
# Two admin-only read endpoints that back the customer-detail Portal
# Access card: current status + recent activity feed.

@router.get("/customers/{cid}/portal-status")
async def portal_status(cid: str, user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    """Compact view of a customer's portal login state for the admin
    Portal Access card.

    Returns::

        {
          "has_login": bool,
          "active": bool,               # false when revoked
          "email": str | None,
          "last_portal_login_at": str | None,
          "last_portal_login_ip": str | None,
          "revoked_at": str | None,
        }
    """
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    cust_user = await db.users.find_one(
        {"customer_id": cid, "tenant_id": tenant["id"], "role": "customer"},
        {"_id": 0},
    )
    return {
        "has_login": bool(cust_user),
        "active": bool(cust_user and cust_user.get("active", True)),
        "email": (cust_user or {}).get("email") or cust.get("email") or None,
        "last_portal_login_at": cust.get("last_portal_login_at"),
        "last_portal_login_ip": cust.get("last_portal_login_ip"),
        "revoked_at": (cust_user or {}).get("revoked_at"),
    }


@router.get("/customers/{cid}/portal-history")
async def portal_history(cid: str,
                           limit: int = 50,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    """Recent portal-related audit events for a single customer:
    portal_login (customer signed in), portal_reset (admin rotated
    password), portal_revoke (admin killed access), and
    impersonation_started / impersonation_ended (admin viewed as
    customer).  Admin-only + tenant-scoped."""
    if not await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
    ):
        raise HTTPException(404, "Customer not found")
    lim = max(1, min(int(limit or 50), 500))
    events = ("portal_login", "portal_reset", "portal_revoke",
              "impersonation_started", "impersonation_ended",
              "admin_password_reset_triggered",
              "admin_password_reset_copied")
    rows = await db.audit_logs.find(
        {"tenant_id": tenant["id"],
          "target_customer_id": cid,
          "event": {"$in": list(events)}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(lim)
    return {
        "customer_id": cid,
        "count": len(rows),
        "events": rows,
    }


# ─── Phase P34 · Feb-2026 — Bulk portal-invite delivery status ────────
@router.get("/admin/portal-invites/delivery-status")
async def portal_invites_delivery_status(
    ids: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase P34 - Feb-2026 - per-customer portal-invite delivery
    lookup.

    Query: ``?ids=cid1,cid2,cid3`` (comma-separated; capped at 200).

    Returns::

        {
          "items": {
            "<customer_id>": {
              "customer_id": "...",
              "email_id": "...",           # Resend id (may be null)
              "recipient": "user@x.com",
              "latest_status": "queued|sent|delivered|bounced|...",
              "latest_status_ts": "2026-02-15T12:00:00+00:00",
            },
            ...
          }
        }

    Tenant-scoped: only rows whose ``tenant_id`` matches the caller's
    tenant are returned; unknown or foreign customer ids yield no
    entry (the FE renders them as ``pending`` locally). Uses the
    ``email_outbox`` correlation table populated by the send path
    and kept fresh by the Resend webhook."""
    cids = [c.strip() for c in (ids or "").split(",") if c.strip()]
    cids = cids[:_H1_BULK_MAX]
    if not cids:
        return {"items": {}}
    tid = tenant["id"]
    cursor = db.email_outbox.find(
        {"tenant_id": tid, "customer_id": {"$in": cids},
         "kind": "portal_invite"},
        {"_id": 0, "email_id": 1, "customer_id": 1, "recipient": 1,
         "latest_status": 1, "latest_status_ts": 1},
    )
    rows = await cursor.to_list(length=len(cids) * 4)
    by_cid: dict = {}
    for r in rows:
        cid = r.get("customer_id")
        if not cid:
            continue
        prev = by_cid.get(cid)
        # Prefer the row with the most-recent status ts. Ties keep the
        # existing row so behaviour is deterministic under duplicates.
        cur_ts = r.get("latest_status_ts") or ""
        prev_ts = (prev or {}).get("latest_status_ts") or ""
        if not prev or cur_ts > prev_ts:
            by_cid[cid] = r
    return {"items": by_cid}




# ─── Phase H1 · Feb-2026 — Bulk portal invite ──────────────────────────
class _H1BulkInviteBody(BaseModel):
    customer_ids: list[str]
    reason: Optional[str] = None


_H1_BULK_MAX = 200
_H1_RATE_WINDOW_SECS = 60 * 60
_H1_RATE_MAX_PER_WINDOW = 500


@router.post("/admin/customers/portal-invite/bulk")
async def portal_invite_bulk(
    body: _H1BulkInviteBody,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase H1 - Feb-2026 - bulk portal invite / password rotate.

    Reuses the single-invite pipeline (``_do_portal_provision``) verbatim
    so send behaviour, audit trail, and idempotency stay in lockstep
    with the ``POST /customers/{cid}/portal-invite`` endpoint that
    already ships. Never parallel - 100ms delay between invites to
    protect upstream provider rate-limits.

    Phase P34 - Feb-2026 - sending pipeline moved to a
    ``BackgroundTasks`` handoff so the HTTP response returns
    immediately (~sub-100ms) even for a 100-customer batch. The
    FE polls ``/api/admin/portal-invites/delivery-status?ids=...``
    to observe per-customer send + delivery progress. Also drops
    the pre-P34 ``has_login=True -> skipped_already_activated``
    branch - every requested id now gets its send attempted; the
    counter key is preserved at 0 for response-shape compat.

    Runs a 100ms sleep between sends to respect RC / Resend
    upstream throttling.

    Rate-limit: 500 invites per tenant per 60-min window, tracked in
    ``db.portal_invite_rate_limit`` (created lazily). Exceeding
    returns 429.  Batch cap: ``_H1_BULK_MAX`` (200); exceeding
    returns 400 forcing the client to page.
    """
    import asyncio
    from datetime import datetime, timezone, timedelta

    tid = tenant["id"]
    ids = [i for i in (body.customer_ids or []) if isinstance(i, str)]
    if not ids:
        raise HTTPException(400, "customer_ids required (non-empty list)")
    if len(ids) > _H1_BULK_MAX:
        raise HTTPException(
            400,
            f"Batch too large ({len(ids)} > {_H1_BULK_MAX}). "
            f"Page the client into batches of {_H1_BULK_MAX} or smaller.",
        )

    # Rate-limit sliding window
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=_H1_RATE_WINDOW_SECS)
    already_sent = await db.portal_invite_rate_limit.count_documents({
        "tenant_id": tid,
        "sent_at": {"$gte": window_start.isoformat()},
    })
    remaining = max(0, _H1_RATE_MAX_PER_WINDOW - already_sent)
    if remaining <= 0:
        raise HTTPException(
            status_code=429,
            detail={
                "detail": "portal_invite_rate_limited",
                "message": (
                    f"Tenant limit of {_H1_RATE_MAX_PER_WINDOW} portal "
                    f"invites per {_H1_RATE_WINDOW_SECS // 60} minutes "
                    f"reached. Try again shortly."
                ),
                "window_seconds": _H1_RATE_WINDOW_SECS,
                "limit": _H1_RATE_MAX_PER_WINDOW,
            },
        )

    batch_id = new_id()
    # Phase P34 · Feb-2026 — pre-flight snapshot so the caller sees a
    # response inside ~50ms. All heavy send I/O runs in the
    # ``BackgroundTasks`` closure below.
    counts = {
        "requested": len(ids),
        "sent": 0,
        # P34: preserved at 0 for response-shape compat. The
        # ``has_login=True`` skip was intentionally removed —
        # already-activated customers now get a fresh password on
        # a bulk-invite request (matches the single-invite path,
        # which is already a "rotate + email" call).
        "skipped_already_activated": 0,
        "skipped_no_contact": 0,
        "skipped_wrong_tenant": 0,
        "failed_send": 0,
    }
    reason_note = (body.reason or "")[:200] or None
    actor_snapshot = {"id": (user or {}).get("id"),
                        "email": (user or {}).get("email")}

    # Hand the sending pipeline off to a background task. FastAPI
    # invokes it AFTER the response is sent, so the client observes
    # a fast return-to-caller.
    background_tasks.add_task(
        _process_portal_invite_bulk,
        ids=list(ids),
        tenant_id=tid,
        actor=actor_snapshot,
        batch_id=batch_id,
        remaining=int(remaining),
        reason_note=reason_note,
    )

    # Response envelope — mirrors the pre-P34 counter keys so
    # existing FE + ChaseStalledInvitesModal consumers keep
    # rendering. ``queued`` is the P34 addition — the number of
    # invite sends that will actually be attempted by the
    # background task.
    payload = {
        **counts,
        "batch_id": batch_id,
        "failures": [],
        # P34 · async response — FE polls
        # ``/api/admin/portal-invites/delivery-status?ids=…`` for
        # per-customer send + Resend delivery progress.
        "queued": len(ids),
        "async": True,
        # Preserve the ChaseStalledInvites shape (enqueued, rate_limited,
        # failed) at zero so the modal doesn't NPE on missing keys.
        "enqueued": 0,
        "rate_limited": [],
        "failed": [],
    }
    return payload


async def _process_portal_invite_bulk(
    *,
    ids: list[str],
    tenant_id: str,
    actor: dict,
    batch_id: str,
    remaining: int,
    reason_note: Optional[str],
) -> None:
    """Phase P34 - Feb-2026 - background sender for the bulk invite
    endpoint. Runs AFTER the HTTP response is dispatched so the
    admin's browser sees an immediate return. Failures are captured
    into the ``audit_events`` row at end-of-batch - no HTTPExceptions
    can bubble out of this coroutine (FastAPI ignores background-task
    exceptions by default; we swallow + log defensively)."""
    counts = {
        "requested": len(ids),
        "sent": 0,
        # P34: ``skipped_already_activated`` intentionally stays 0 —
        # kept as a key for backward-compat with downstream consumers
        # of the audit_events payload.
        "skipped_already_activated": 0,
        "skipped_no_contact": 0,
        "skipped_wrong_tenant": 0,
        "failed_send": 0,
    }
    failures: list[dict] = []
    seen: set = set()

    for cid in ids:
        if cid in seen:
            counts["skipped_already_activated"] += 1
            continue
        seen.add(cid)

        if counts["sent"] >= remaining:
            failures.append({
                "customer_id": cid,
                "reason": "rate_limit_mid_batch",
            })
            counts["failed_send"] += 1
            continue

        cust = await db.customers.find_one(
            {"id": cid}, {"_id": 0, "id": 1, "tenant_id": 1,
                          "email": 1, "phone": 1, "has_login": 1},
        )
        if not cust or cust.get("tenant_id") != tenant_id:
            counts["skipped_wrong_tenant"] += 1
            failures.append({
                "customer_id": cid,
                "reason": "wrong_tenant_or_missing",
            })
            continue
        # Phase P34 · dropped the ``has_login=True → skip``
        # branch. Already-activated customers now get a fresh
        # temp password on a bulk-invite call. See the docstring
        # of ``portal_invite_bulk`` for rationale.
        if not (cust.get("email") or "").strip() and \
                not (cust.get("phone") or "").strip():
            counts["skipped_no_contact"] += 1
            failures.append({
                "customer_id": cid,
                "reason": "no_email_or_phone",
            })
            continue

        try:
            await _do_portal_provision(
                cid, tenant_id, actor, explicit_password=None,
            )
            counts["sent"] += 1
            await db.portal_invite_rate_limit.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "customer_id": cid,
                "batch_id": batch_id,
                "actor_id": actor.get("id"),
                "sent_at": now_iso(),
            })
        except HTTPException as exc:
            counts["failed_send"] += 1
            failures.append({
                "customer_id": cid,
                "reason": "http_error",
                "error": str(exc.detail)[:200],
            })
        except Exception as exc:  # noqa: BLE001
            counts["failed_send"] += 1
            failures.append({
                "customer_id": cid,
                "reason": "exception",
                "error": str(exc)[:200],
            })
        await asyncio.sleep(0.1)

    payload = {
        **counts,
        "batch_id": batch_id,
        "failures": failures,
        "enqueued": counts["sent"],
        "rate_limited": [
            f["customer_id"] for f in failures
            if f.get("reason") == "rate_limit_mid_batch"
        ],
        "failed": [
            {"id": f["customer_id"], "reason": f.get("reason") or "unknown"}
            for f in failures
            if f.get("reason") != "rate_limit_mid_batch"
        ],
    }
    try:
        await db.audit_events.insert_one({
            "id": new_id(),
            "event_type": "portal_invite_bulk",
            "tenant_id": tenant_id,
            "actor_id": actor.get("id"),
            "actor_email": actor.get("email"),
            "reason": reason_note,
            "timestamp": now_iso(),
            "payload": {k: v for k, v in payload.items() if k != "failures"},
            "failure_count": len(failures),
        })
    except Exception as _ae:  # noqa: BLE001
        logger.warning(
            f"[phase-h1] audit_events insert failed: {_ae}",
        )


# ═════════════════════════════════════════════════════════════════════
# LEGACY PATH — the pre-P34 synchronous body kept ONLY for legacy
# consumers that read the ``failures`` array off the immediate HTTP
# response. The path is now unreachable from the FastAPI dispatcher
# because the decorator above owns the route registration. Removing
# this stub is a follow-up cleanup.
# ═════════════════════════════════════════════════════════════════════
async def _portal_invite_bulk_legacy_unreachable(
    body: _H1BulkInviteBody,
    user: dict,
    tenant: dict,
    _tid: str,
    _ids: list,
    _remaining: int,
) -> dict:
    tid = _tid
    ids = _ids
    remaining = _remaining
