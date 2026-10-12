"""Feb-2026 · Marketing Slice M3 — Reusable per-tenant email + SMS
template library.

Storage is a new ``marketing_templates`` collection.  Rendering is a
tiny Mustache-style substituter (regex ``{{[\\w.]+}}`` walking the
dotted path in a context dict) so we don't drag Jinja / Chevron into
the runtime.  See ``services/marketing/render.py`` for the pure
renderer + unit tests.

Coexists with the pre-existing ``/marketing/templates/{campaigns|
emails|sms|lint|preview}`` static-path routes in
``routers/marketing_studio.py`` and ``routers/marketing_campaigns.py``.
Order of registration in ``server.py`` ensures those static paths win
over the M3 dynamic ``{tid}`` capture.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant
from services.marketing.render import (
    render_template,
    render_subject_and_body,
    strip_html,
    DEFAULT_SAMPLE_CONTEXT,
    VARIABLES_REGISTRY,
)
# Phase 9 · Feb 2026 — uppercase merge-tag catalog + universal renderer.
from services.marketing.merge_tags import (
    render_template as render_uppercase_tags,
    catalog_grouped as merge_tags_catalog,
    catalog_flat as merge_tags_catalog_flat,
    render_context as build_merge_ctx,
)
# Phase 9 · Feb 2026 — canonical outbound email adapter. Imported at
# module load so a broken path fails FAST at boot instead of only when
# a user hits the ``test-send`` endpoint.
from services.email.resend_adapter import send as _resend_send
# SAFE-SEND-C · Feb-2026 — the test-send endpoint passes
# ``CommsContext.TEST`` into the adapter so AGENT/TEST redirects to
# the tenant admin sandbox instead of the caller-supplied recipient.
from services.comms_env_guard import CommsContext

router = APIRouter()


ALLOWED_CHANNELS = {"email", "sms"}
ALLOWED_CATEGORIES = {
    "service_completed", "invoice_sent", "past_due",
    "welcome", "review_request", "general",
    # TE-portal-job · Feb-2026 — transactional trigger categories
    # backed by ``marketing_templates`` rows with ``code=
    # portal_invite_email`` and ``code=job_completion_sms``. Seeded
    # by ``migrations/te_portal_job_templates_seed.py``.
    "portal_invite", "job_completion",
    # Feb-2026 · Quote/Estimate email seed — one system-default row
    # per tenant with ``system_key=quote_estimate_email``. Seeded by
    # ``services/migrations/seed_quote_estimate_template.py``.
    "quotes",
}


class TemplateIn(BaseModel):
    # P1-M3-HARDENING · Feb-2026 — ``populate_by_name`` lets a legacy
    # or alias field name on an incoming payload still bind to its
    # canonical model field. Preventive measure in case a prod caller
    # ships ``body_html`` (rich-editor convention mirrored on
    # ``TemplatePatch``) on the create path instead of ``body``.
    model_config = {"populate_by_name": True}
    name: str = Field(..., min_length=1, max_length=120)
    channel: str
    category: str = "general"
    subject: Optional[str] = None
    body: str = ""
    # ``body_html`` is a first-class alias for ``body`` on create too
    # (matches the PATCH-time behavior added in Phase 9). If BOTH are
    # supplied, explicit ``body`` wins. See ``create_template`` below.
    body_html: Optional[str] = None
    active: bool = True


class TemplatePatch(BaseModel):
    name: Optional[str] = None
    channel: Optional[str] = None
    category: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    # Phase 9 · Feb 2026 — TipTap and other rich-HTML editors on the
    # frontend send the compiled markup as ``body_html``. Accept it as
    # a first-class alias for ``body`` so a stray field name never
    # silently drops user content. If BOTH are supplied, ``body``
    # wins (explicit trumps alias). See ``patch_template`` below.
    body_html: Optional[str] = None
    active: Optional[bool] = None


def _validate_shape(channel: str, subject: Optional[str]) -> None:
    if channel not in ALLOWED_CHANNELS:
        raise HTTPException(422, f"channel must be one of {sorted(ALLOWED_CHANNELS)}")
    if channel == "email" and not (subject or "").strip():
        raise HTTPException(422, "Email templates require a subject")


def _serialize(row: dict) -> dict:
    row = dict(row)
    row.pop("_id", None)
    return row


# ─────────────────────────────────────────────────────────────────────
# P1-M3-HARDENING · Feb-2026 — Lazy, idempotent index ensure. The
# marketing_templates list query filters by ``tenant_id`` (always) +
# ``channel`` + sorts by ``updated_at`` DESC. A compound covering
# index keeps pagination fast as tenants accumulate templates.
# ``create_index`` is a no-op when the exact index already exists.
# ─────────────────────────────────────────────────────────────────────
_indexes_ensured = False


async def _ensure_indexes_once() -> None:
    global _indexes_ensured
    if _indexes_ensured:
        return
    try:
        await db.marketing_templates.create_index(
            [("tenant_id", 1), ("channel", 1), ("updated_at", -1)],
            name="mt_tenant_channel_updated_desc",
            background=True,
        )
        _indexes_ensured = True
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "[marketing-templates] index ensure skipped: %s", exc,
        )


# ═══════════════════════════════════════════════════════════════════════
# Static-path routes FIRST — declared before ``{tid}`` capture below.
# ═══════════════════════════════════════════════════════════════════════
@router.get("/marketing/templates/variables")
async def list_variables(user: dict = Depends(require_admin)):
    """Return the registry of supported Mustache variables so the UI
    can render an insert-variable dropdown."""
    return {"variables": VARIABLES_REGISTRY}


@router.get("/marketing/merge-tags")
async def list_merge_tags(user: dict = Depends(get_current_user)):
    """Phase 9 · Feb 2026 — canonical UPPERCASE merge-tag catalog.

    Grouped by category (Customer / Company / Estimate / Invoice /
    Payment / Portal / Event / Employee / System) for the insert-tag
    palette. Every send-time template can consume any tag returned
    here via ``{{TOKEN}}`` — case- and whitespace-tolerant."""
    if user.get("role") not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, "Not allowed")
    return {"categories": merge_tags_catalog()}


@router.get("/merge-tags")
async def list_merge_tags_flat(user: dict = Depends(get_current_user)):
    """M-TAG-FIX · Feb-2026 — flat merge-tag registry alias.

    Companion to ``GET /api/marketing/merge-tags`` for the visual
    email builder prerequisite. Returns a FLAT list (not grouped)
    with the ``{key, label, description, category, sample_value}``
    item shape so the builder's dropdown can lazy-render the full
    catalog without a client-side flatten pass. Admin/manager-only,
    same auth as the grouped endpoint.
    """
    if user.get("role") not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, "Not allowed")
    return {"tags": merge_tags_catalog_flat()}


@router.post("/marketing/templates/{tid}/revert")
async def revert_template(
    tid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase 9 · Feb 2026 — restore a system-seeded template from its
    ``factory_defaults`` snapshot. Available for both system and user-
    edited-system templates. Non-system templates return 400."""
    row = await db.marketing_templates.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Template not found")
    fd = row.get("factory_defaults") or {}
    if not fd:
        raise HTTPException(400, "No factory defaults snapshot for this template")
    patch = {
        "name": fd.get("name") or row.get("name"),
        "channel": fd.get("channel") or row.get("channel"),
        "category": fd.get("category") or row.get("category"),
        "subject": fd.get("subject"),
        "body": fd.get("body") or "",
        "active": True,
        "updated_at": now_iso(),
    }
    await db.marketing_templates.update_one({"id": tid}, {"$set": patch})
    row.update(patch)
    return row


@router.get("/marketing/templates")
async def list_templates(
    channel: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
    # P1-M3-HARDENING · Feb-2026 — opt-in pagination. When EITHER
    # ``page`` or ``size`` is supplied the response adds the
    # ``items / total / page / size / has_next`` envelope keys. The
    # legacy ``templates / count`` keys are KEPT ALONGSIDE so existing
    # callers (MassMessaging composer, Sequences, Review Requests,
    # Forms, CustomerDetail, legacy Library page) keep working
    # verbatim. When neither param is supplied the response is
    # exactly as before (up to 500 rows).
    page: Optional[int] = Query(None, ge=1),
    size: Optional[int] = Query(None, ge=1, le=500),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    try:
        await _ensure_indexes_once()
        q: Dict[str, Any] = {"tenant_id": tenant["id"]}
        if channel:
            q["channel"] = channel
        if category:
            q["category"] = category
        if active is not None:
            q["active"] = active

        if page is not None or size is not None:
            eff_page = page or 1
            eff_size = size or 50
            total = await db.marketing_templates.count_documents(q)
            skip = (eff_page - 1) * eff_size
            rows = await db.marketing_templates.find(q, {"_id": 0}).sort(
                [("system", -1), ("updated_at", -1)],
            ).skip(skip).limit(eff_size).to_list(eff_size)
            has_next = (skip + len(rows)) < total
            return {
                "items": rows,
                "total": total,
                "page": eff_page,
                "size": eff_size,
                "has_next": has_next,
                # Legacy aliases — do NOT remove without a FE sweep.
                "templates": rows,
                "count": len(rows),
            }

        rows = await db.marketing_templates.find(q, {"_id": 0}).sort(
            [("system", -1), ("updated_at", -1)],
        ).to_list(500)
        return {"templates": rows, "count": len(rows)}
    except HTTPException:
        raise
    except Exception as exc:
        # P1-M3-HARDENING · Feb-2026 — Any uncaught exception on list
        # MUST surface as a 500 with a specific ``error_code`` so the
        # admin UI can render the actual failure instead of a bare
        # proxy 502. Full stack trace is logged at ERROR level.
        logger.exception(
            "[marketing-templates] list failed for tenant %s: %s",
            tenant.get("id"), exc,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "marketing_template_list_internal_error",
                "message": (
                    f"Could not load templates ({type(exc).__name__}). "
                    "Please retry; if the problem persists, contact "
                    "support."
                ),
            },
        )


@router.post("/marketing/templates", status_code=201)
async def create_template(
    body: TemplateIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    _validate_shape(body.channel, body.subject)
    try:
        # P1-M3-HARDENING · Feb-2026 — ``body_html`` is a first-class
        # alias for ``body`` on create (rich-editor payloads). If the
        # explicit ``body`` field is empty AND ``body_html`` arrived,
        # the alias wins so no user content gets silently dropped.
        resolved_body = body.body
        if not (resolved_body or "").strip() and body.body_html:
            resolved_body = body.body_html

        doc = {
            "id": new_id(),
            "tenant_id": tenant["id"],
            "name": body.name.strip(),
            "channel": body.channel,
            "category": body.category or "general",
            "subject": (body.subject or "").strip() if body.channel == "email" else None,
            "body": resolved_body or "",
            "active": bool(body.active),
            "system": False,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "created_by": user.get("id"),
        }
        await db.marketing_templates.insert_one(doc)
        return _serialize(doc)
    except HTTPException:
        raise
    except Exception as exc:
        # P1-M3-HARDENING · Feb-2026 — Any uncaught exception on
        # create MUST surface as a 500 with a specific ``error_code``
        # so the admin never sees a bare proxy 502. Full stack trace
        # is logged at ERROR level so the admin can file a ticket
        # with correlation data.
        logger.exception(
            "[marketing-templates] create failed for tenant %s: %s",
            tenant.get("id"), exc,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "marketing_template_create_internal_error",
                "message": (
                    f"Could not create template ({type(exc).__name__}). "
                    "Please retry; if the problem persists, contact "
                    "support."
                ),
            },
        )


# ═══════════════════════════════════════════════════════════════════════
# ``{tid}``-scoped routes below.  Static slugs above already claimed
# their names, so an incoming ``/marketing/templates/variables`` still
# resolves to ``list_variables`` — not to ``get_template("variables")``.
# ═══════════════════════════════════════════════════════════════════════
@router.get("/marketing/templates/{tid}")
async def get_template(
    tid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.marketing_templates.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Template not found")
    return row


@router.patch("/marketing/templates/{tid}")
async def patch_template(
    tid: str,
    body: TemplatePatch,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.marketing_templates.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Template not found")
    patch: Dict[str, Any] = {}
    # Phase 9 · Feb 2026 — ``body_html`` is a first-class alias for
    # ``body`` (rich HTML editors ship the payload under that name).
    # If both are provided, explicit ``body`` wins.
    if body.body is None and body.body_html is not None:
        patch["body"] = body.body_html
    for field in ("name", "channel", "category", "subject", "body", "active"):
        val = getattr(body, field)
        if val is not None:
            patch[field] = val
    if not patch:
        return row
    if "channel" in patch or "subject" in patch:
        _validate_shape(
            patch.get("channel", row["channel"]),
            patch.get("subject", row.get("subject")),
        )
    if patch.get("channel") == "sms":
        patch["subject"] = None
    patch["updated_at"] = now_iso()
    await db.marketing_templates.update_one({"id": tid}, {"$set": patch})
    row.update(patch)
    return row


@router.delete("/marketing/templates/{tid}", status_code=204)
async def delete_template(
    tid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Soft-delete: set ``active=false``.  If any live campaign
    (``scheduled`` or ``running``) references this template, we 409 to
    protect against yanking a template out from under an active send.
    """
    row = await db.marketing_templates.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Template not found")
    live = await db.marketing_campaigns.count_documents({
        "tenant_id": tenant["id"],
        "$or": [
            {"template_id": tid},
            {"email_template_id": tid},
            {"sms_template_id": tid},
        ],
        "status": {"$in": ["scheduled", "running"]},
    })
    if live:
        raise HTTPException(
            409,
            f"Template referenced by {live} live campaign(s) — "
            f"pause or cancel them before deleting.",
        )
    await db.marketing_templates.update_one(
        {"id": tid},
        {"$set": {"active": False, "updated_at": now_iso()}},
    )
    from fastapi import Response
    return Response(status_code=204)


class PreviewBody(BaseModel):
    sample_context: Optional[Dict[str, Any]] = None


@router.post("/marketing/templates/{tid}/preview")
async def preview_template(
    tid: str,
    body: PreviewBody = PreviewBody(),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.marketing_templates.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Template not found")
    # Merge caller-provided context on top of the canned default so
    # missing keys still render sensibly.
    ctx = dict(DEFAULT_SAMPLE_CONTEXT)
    if body.sample_context:
        # Shallow-merge — the caller can override any top-level key.
        for k, v in body.sample_context.items():
            if isinstance(v, dict) and isinstance(ctx.get(k), dict):
                merged = dict(ctx[k])
                merged.update(v)
                ctx[k] = merged
            else:
                ctx[k] = v

    # Phase 9 · Feb 2026 — run the UPPERCASE renderer FIRST so
    # ``{{CUSTOMER_FIRST_NAME}}`` substitutes before the legacy
    # Mustache pass has a chance to null it out. The legacy pass
    # then handles any remaining ``{{customer.first_name}}`` dotted
    # tokens.
    # Aug-2026 · Preview-fidelity fix — forward the sample context's
    # ``job``, ``event``, ``service_report`` sub-dicts AND the extended
    # customer address block so Job / Event / Service-record merge
    # tags (SERVICE_TITLE, SERVICE_NAME, JOB_DATE, JOB_TIME,
    # EVENT_TITLE, EVENT_NOTES, SERVICE_RECORD_IMAGES, CUSTOMER_ADDRESS)
    # resolve in the composer preview instead of being flagged as
    # unresolved. Backward-compatible: unset keys forward as empty.
    demo_ctx = build_merge_ctx(
        customer={
            # Feb 2026 · Preview-fidelity fix — forward ``id`` so the
            # CUSTOMER_PORTAL_LOGIN_LINK / SERVICE_RECORD_LINK
            # resolvers can mint their preview magic URLs instead of
            # rendering empty. The whitelist previously dropped ``id``
            # entirely, so both tags fell through to "unresolved" in
            # the composer preview even though real sends work fine.
            "id": (ctx.get("customer") or {}).get("id"),
            "name": ((ctx.get("customer") or {}).get("first_name", "") + " "
                     + (ctx.get("customer") or {}).get("last_name", "")).strip(),
            "first_name": (ctx.get("customer") or {}).get("first_name"),
            "last_name": (ctx.get("customer") or {}).get("last_name"),
            # Aug-2026 · dot-notation preview fix — legacy Mustache
            # templates use ``{{customer.full_name}}`` (and neighbours).
            # Preserve the original key so the renderer's Step-2
            # nested-dotted lookup finds it. The catalog UPPERCASE
            # path (CUSTOMER_FULL_NAME) already worked because it has
            # its own resolver.
            "full_name": (ctx.get("customer") or {}).get("full_name"),
            "email": (ctx.get("customer") or {}).get("email"),
            "phone": (ctx.get("customer") or {}).get("phone"),
            # Aug-2026 · dot-notation preview fix — the ``balance_due``
            # key was previously renamed to ``open_balance`` during
            # this reshuffle so ``{{customer.balance_due}}`` couldn't
            # walk the nested lookup. Keep BOTH keys so:
            #   • ``{{CUSTOMER_ACCOUNT_BALANCE}}`` (catalog resolver
            #     reads ``open_balance``) — unchanged.
            #   • ``{{customer.balance_due}}`` (dot-notation) — now
            #     resolves to the original sample value.
            "open_balance": (ctx.get("customer") or {}).get("balance_due", 0),
            "balance_due": (ctx.get("customer") or {}).get("balance_due"),
            # Address fields — CUSTOMER_ADDRESS / CUSTOMER_STREET /
            # CUSTOMER_CITY / CUSTOMER_STATE / CUSTOMER_ZIP resolvers.
            "address_line_1": (ctx.get("customer") or {}).get("address_line_1"),
            "address": (ctx.get("customer") or {}).get("address"),
            "city": (ctx.get("customer") or {}).get("city"),
            "state": (ctx.get("customer") or {}).get("state"),
            "zip": (ctx.get("customer") or {}).get("zip"),
        },
        tenant=ctx.get("tenant") or {},
        invoice=ctx.get("invoice"),
        job=ctx.get("job"),
        event=ctx.get("event"),
        service_report=ctx.get("service_report"),
        # Aug-2026 · flat top-level keys used by legacy dotted-style
        # templates (``{{next_service_date}}``, ``{{next_service_type}}``)
        # AND UPPERCASE fallthrough (``{{NEXT_SERVICE_DATE}}``). These
        # aren't Catalog-registered tags but the resolver's flat-key
        # cascade honors them — they just need to survive the demo_ctx
        # reshuffle. ``build_merge_ctx`` accepts ``**extra`` so we
        # pass any flat keys through verbatim.
        next_service_date=ctx.get("next_service_date"),
        next_service_type=ctx.get("next_service_type"),
        # ADD_CARD_LINK resolver reads flat ``ctx["add_card_link"]``.
        add_card_link=ctx.get("add_card_link"),
        # Feb 2026 · Preview-fidelity fix — flag the render as a
        # preview so the CUSTOMER_PORTAL_LOGIN_LINK / SERVICE_RECORD_LINK
        # resolvers mint tokens with ``preview: True``. Those tokens
        # look like real URLs in the composer preview pane but are
        # rejected at redemption (400 preview_token_cannot_be_redeemed)
        # so an accidentally-copied preview link can never grant a real
        # session.
        _is_preview=True,
    )
    pre_subject, sub_missing = render_uppercase_tags(row.get("subject") or "", demo_ctx)
    pre_body, body_missing = render_uppercase_tags(row.get("body") or "", demo_ctx)
    unresolved_tokens = sorted(set(list(sub_missing) + list(body_missing)))

    subject_rendered, body_rendered, missing = render_subject_and_body(
        pre_subject, pre_body, ctx,
    )
    # SMS strips any HTML that leaked in from a copy-paste — email
    # keeps it verbatim (email clients render inline HTML).
    if row.get("channel") == "sms":
        body_rendered = strip_html(body_rendered)

    return {
        "subject_rendered": subject_rendered if row.get("channel") == "email" else None,
        "body_rendered": body_rendered,
        "missing_vars": sorted(set(missing)),
        "unresolved_tokens": unresolved_tokens,
    }


# ═══════════════════════════════════════════════════════════════════════
# Phase 9 · Feb 2026 — Test-send endpoint
# ═══════════════════════════════════════════════════════════════════════
import asyncio as _phase9_asyncio
import time as _phase9_time
from collections import defaultdict as _phase9_dd

_TEST_SEND_LIMIT = 5
_TEST_SEND_WINDOW_S = 60.0
_test_send_hits: Dict[str, List[float]] = _phase9_dd(list)
_test_send_lock = _phase9_asyncio.Lock()


async def _rate_limit_test_send(user_id: str) -> None:
    now = _phase9_time.monotonic()
    async with _test_send_lock:
        bucket = _test_send_hits[user_id]
        cutoff = now - _TEST_SEND_WINDOW_S
        i = 0
        while i < len(bucket) and bucket[i] < cutoff:
            i += 1
        if i:
            del bucket[:i]
        if len(bucket) >= _TEST_SEND_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=(f"Rate limit — max {_TEST_SEND_LIMIT} test sends "
                          "/ minute"),
            )
        bucket.append(now)


@router.post("/marketing/templates/_test-send-rate-reset")
async def test_send_rate_reset(user: dict = Depends(require_admin)):
    """Phase 9 · Feb 2026 — admin-only reset of the caller's
    test-send rate-limit bucket. Exists so pytest can prove the 5/min
    gate deterministically without waiting 60 seconds between runs."""
    async with _test_send_lock:
        _test_send_hits.pop(user.get("id") or "anon", None)
    return {"ok": True}


class TemplateTestSendBody(BaseModel):
    to: str = Field(..., description="Recipient email (email templates) "
                                       "or phone (SMS templates)")
    sample_context: Optional[Dict[str, Any]] = None


@router.post("/marketing/templates/{tid}/test-send")
async def test_send_template(
    tid: str, body: TemplateTestSendBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase 9 · Feb 2026 — send a live email or SMS preview to a
    specific recipient using the merge-tag renderer.

    * Admin / super_admin / manager only.
    * Rate-limited to 5 sends / minute / user (returns 429 on the 6th
      request inside a 60-second window). Rate limit resets naturally
      as calls age out.
    * Uses the SAME code path production sends do — Resend for email,
      RingCentral adapter for SMS — so a successful test send is
      *proof* the tenant's outbound wiring works end-to-end.
    * Both uppercase merge tags (Phase 9) and legacy Mustache tags
      substitute before the send.
    """
    if user.get("role") not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, "Not allowed")
    await _rate_limit_test_send(user.get("id") or "anon")

    row = await db.marketing_templates.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Template not found")

    to_field = (body.to or "").strip()
    if not to_field:
        raise HTTPException(400, "Recipient 'to' is required")

    ctx_in = body.sample_context or DEFAULT_SAMPLE_CONTEXT
    # Aug-2026 · Preview-fidelity fix — mirrors the /preview endpoint
    # change so test-sends use the same enriched sample context as the
    # composer preview. Job / Event / Service-record tags now resolve
    # in test-send rendering when the caller omits sample_context.
    demo_ctx = build_merge_ctx(
        customer={
            "name": ((ctx_in.get("customer") or {}).get("first_name", "") + " "
                     + (ctx_in.get("customer") or {}).get("last_name", "")).strip(),
            "first_name": (ctx_in.get("customer") or {}).get("first_name"),
            "last_name": (ctx_in.get("customer") or {}).get("last_name"),
            "full_name": (ctx_in.get("customer") or {}).get("full_name"),
            "email": to_field if row.get("channel") == "email" else (ctx_in.get("customer") or {}).get("email"),
            "phone": to_field if row.get("channel") == "sms" else (ctx_in.get("customer") or {}).get("phone"),
            "open_balance": (ctx_in.get("customer") or {}).get("balance_due", 0),
            "balance_due": (ctx_in.get("customer") or {}).get("balance_due"),
            "address_line_1": (ctx_in.get("customer") or {}).get("address_line_1"),
            "address": (ctx_in.get("customer") or {}).get("address"),
            "city": (ctx_in.get("customer") or {}).get("city"),
            "state": (ctx_in.get("customer") or {}).get("state"),
            "zip": (ctx_in.get("customer") or {}).get("zip"),
        },
        tenant=ctx_in.get("tenant") or {"name": tenant.get("name")},
        invoice=ctx_in.get("invoice"),
        job=ctx_in.get("job"),
        event=ctx_in.get("event"),
        service_report=ctx_in.get("service_report"),
        next_service_date=ctx_in.get("next_service_date"),
        next_service_type=ctx_in.get("next_service_type"),
        add_card_link=ctx_in.get("add_card_link"),
    )
    pre_subject, sub_missing = render_uppercase_tags(
        row.get("subject") or "", demo_ctx,
    )
    pre_body, body_missing = render_uppercase_tags(
        row.get("body") or "", demo_ctx,
    )
    subject_rendered, body_rendered, missing = render_subject_and_body(
        pre_subject, pre_body, ctx_in,
    )

    channel = row.get("channel")
    provider_res: Dict[str, Any] = {"provider": "unknown"}

    if channel == "sms":
        if "@" in to_field or "+" not in to_field and not to_field.isdigit():
            # Best-effort input hygiene — RC adapter's normaliser is
            # the source of truth so we just warn on obvious mistakes.
            logger.warning(
                f"[phase9-test-send] SMS to-field looks odd: '{to_field}'"
            )
        rendered_plain = strip_html(body_rendered)
        try:
            from services.sms.rc_adapter import send as _rc_send
            provider_res = await _rc_send(
                to=to_field, body=rendered_plain,
                category="transactional", tenant_id=tenant["id"],
                idempotency_key=(f"tpl-testsend:{tid}:{user.get('id')}:"
                                    f"{int(_phase9_time.time())}"),
                # SAFE-SEND-C · Feb-2026 — TEST context redirects the
                # send to the tenant admin sandbox and enriches the
                # returned envelope with the six safe-send fields.
                context=CommsContext.TEST,
            )
        except Exception as exc:  # pragma: no cover
            provider_res = {"provider": "ringcentral",
                             "provider_status": "failed",
                             "provider_response_id": None,
                             "error": str(exc)}
        return {
            "ok": provider_res.get("provider_status") in (
                "sent", "queued", "mocked", "dry_run",
            ),
            "channel": "sms",
            "recipient": to_field,
            "provider": provider_res.get("provider"),
            "provider_status": provider_res.get("provider_status"),
            "provider_response_id": provider_res.get("provider_response_id"),
            "rendered_body": rendered_plain,
            "unresolved_tokens": sorted(set(list(sub_missing) + list(body_missing))),
            "missing_vars": sorted(set(missing)),
            # SAFE-SEND-C · Feb-2026 — expose the safe-send envelope
            # so the FE test-send badge (SAFE-SEND-B) can render the
            # "redirected to admin" state and the audit-metadata pair.
            "redirected": provider_res.get("redirected", False),
            "safe_send_context": provider_res.get(
                "safe_send_context", CommsContext.TEST.value,
            ),
            "intended_recipient_redacted": provider_res.get(
                "intended_recipient_redacted",
            ),
            "actual_recipient_redacted": provider_res.get(
                "actual_recipient_redacted",
            ),
            "was_mock": provider_res.get("provider") == "mock",
        }

    # ─── email
    if "@" not in to_field:
        raise HTTPException(400, "Email 'to' must be a valid address")
    # Phase 9 · Feb 2026 — Resend is the single canonical outbound
    # email adapter. ``_resend_send`` is imported at module top so a
    # broken adapter fails at boot, not on the 6th user click. Only
    # RUNTIME send errors are caught here — never import errors.
    try:
        provider_res = await _resend_send(
            to=to_field, subject=subject_rendered or "(test)",
            html=body_rendered or "",
            category="transactional", tenant_id=tenant["id"],
            # SAFE-SEND-C · Feb-2026 — TEST context redirects the
            # send to the tenant admin sandbox and enriches the
            # returned envelope with the six safe-send fields.
            context=CommsContext.TEST,
        )
    except Exception as exc:
        logger.exception(
            "[phase9-test-send] email send raised for template %s to %s",
            tid, to_field,
        )
        provider_res = {
            "provider": "resend",
            "provider_status": "failed",
            "provider_response_id": None,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
    return {
        "ok": provider_res.get("provider_status") in (
            "sent", "queued", "mocked", "dry_run",
        ),
        "channel": "email",
        "recipient": to_field,
        "provider": provider_res.get("provider"),
        "provider_status": provider_res.get("provider_status"),
        "provider_response_id": provider_res.get("provider_response_id"),
        "rendered_subject": subject_rendered,
        "rendered_body": body_rendered,
        "unresolved_tokens": sorted(set(list(sub_missing) + list(body_missing))),
        "missing_vars": sorted(set(missing)),
        "error_type": provider_res.get("error_type"),
        "error_message": provider_res.get("error_message") or provider_res.get("error"),
        # SAFE-SEND-C · Feb-2026 — expose the safe-send envelope so
        # the FE test-send badge (SAFE-SEND-B) can render the
        # "redirected to admin" state and the audit-metadata pair.
        "redirected": provider_res.get("redirected", False),
        "safe_send_context": provider_res.get(
            "safe_send_context", CommsContext.TEST.value,
        ),
        "intended_recipient_redacted": provider_res.get(
            "intended_recipient_redacted",
        ),
        "actual_recipient_redacted": provider_res.get(
            "actual_recipient_redacted",
        ),
        "was_mock": provider_res.get("provider") == "mock",
    }


# ═══════════════════════════════════════════════════════════════════════
# Seed
# ═══════════════════════════════════════════════════════════════════════
DEFAULT_SEED = [
    # (category, name, subject|None, body, channel)
    ("service_completed", "Service Completed — Email", "Your service is done, {{customer.first_name}}!",
     "Hi {{customer.first_name}},\n\nWe just wrapped up your {{next_service_type}} visit. If you have any questions, hit reply.\n\n— The {{tenant.name}} team", "email"),
    ("service_completed", "Service Completed — SMS", None,
     "Hi {{customer.first_name}}, {{tenant.name}} just finished your visit. Call {{tenant.phone}} with any questions.", "sms"),

    ("invoice_sent", "Invoice Sent — Email", "Your latest invoice from {{tenant.name}}",
     "Hi {{customer.first_name}},\n\nYour balance due is {{customer.balance_due}}. Log in to your portal to review or pay.\n\nThanks!", "email"),
    ("invoice_sent", "Invoice Sent — SMS", None,
     "Hi {{customer.first_name}}, {{tenant.name}} sent you a new invoice. Balance: {{customer.balance_due}}.", "sms"),

    ("past_due", "Past-Due Reminder — Email", "A quick reminder about your balance",
     "Hi {{customer.first_name}},\n\nOur records show a past-due balance of {{customer.balance_due}}. Let us know if there's anything we can help with.\n\n— {{tenant.name}}", "email"),
    ("past_due", "Past-Due Reminder — SMS", None,
     "Hi {{customer.first_name}}, {{tenant.name}} — a friendly nudge on your balance of {{customer.balance_due}}.", "sms"),

    ("welcome", "Welcome — Email", "Welcome to {{tenant.name}}, {{customer.first_name}}!",
     "Hi {{customer.first_name}},\n\nWe're glad to have you on board. Your first visit is booked for {{next_service_date}}.\n\n— The {{tenant.name}} team", "email"),
    ("welcome", "Welcome — SMS", None,
     "Welcome to {{tenant.name}}, {{customer.first_name}}! Your first visit is on {{next_service_date}}.", "sms"),

    ("review_request", "Review Request — Email", "How did we do, {{customer.first_name}}?",
     "Hi {{customer.first_name}},\n\nIf we did a good job, we'd really appreciate a review: {{tenant.google_review_url}}\n\n— {{tenant.name}}", "email"),
    ("review_request", "Review Request — SMS", None,
     "Hi {{customer.first_name}}, would you leave {{tenant.name}} a quick review? {{tenant.google_review_url}}", "sms"),

    ("general", "General Update — Email", "An update from {{tenant.name}}",
     "Hi {{customer.first_name}},\n\n[Write your message here]\n\n— The {{tenant.name}} team", "email"),
    ("general", "General Update — SMS", None,
     "Hi {{customer.first_name}}, this is {{tenant.name}} — [your message here].", "sms"),
]


async def seed_marketing_templates_for_tenant(tenant_id: str) -> int:
    """Idempotent per-tenant seed. Only inserts if the tenant has zero
    templates today — never overwrites admin edits."""
    count = await db.marketing_templates.count_documents(
        {"tenant_id": tenant_id},
    )
    if count > 0:
        return 0
    now = now_iso()
    docs = []
    for category, name, subject, body, channel in DEFAULT_SEED:
        docs.append({
            "id": new_id(),
            "tenant_id": tenant_id,
            "name": name,
            "channel": channel,
            "category": category,
            "subject": subject,
            "body": body,
            "active": True,
            "system": True,       # ``system=true`` templates can be
                                   # duplicated but not hard-deleted.
            "is_editable": True,   # Phase 9 · Feb 2026 — every
                                   # template is editable; the old
                                   # read-only gate is retired.
            "factory_defaults": {  # Phase 9 · Feb 2026 — snapshot for
                                   # "Revert to default".
                "name": name, "channel": channel, "category": category,
                "subject": subject, "body": body,
            },
            "created_at": now,
            "updated_at": now,
            "created_by": None,
        })
    if docs:
        await db.marketing_templates.insert_many(docs)
    return len(docs)


async def seed_marketing_templates_all_tenants() -> Dict[str, int]:
    total = 0
    tenants = 0
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        tenants += 1
        try:
            total += await seed_marketing_templates_for_tenant(t["id"])
        except Exception as exc:  # pragma: no cover
            logger.warning("m3 seed for tenant %s failed: %s", t.get("id"), exc)
    return {"tenants": tenants, "inserted": total}
