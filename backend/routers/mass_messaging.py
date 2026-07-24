"""Phase 15 · Feb-2026 — Mass Text + Email broadcast.

Admin-only one-click broadcast to every active customer via email +
SMS (or both). Leans hard on existing infrastructure so nothing new
is invented:

* Templates → ``db.marketing_templates`` (Phase 9 canonical schema).
* Rendering → ``services.marketing.merge_tags.render_template``.
* Suppression → ``routers.marketing_preferences.is_suppressed``.
* Adapters   → ``services.email.resend_adapter`` +
              ``services.sms.rc_adapter`` (route through the same
              transactional path every other feature uses).
* Ledger     → ``db.marketing_deliveries`` with
              ``trigger_entity.kind == "mass_broadcast"``.

Guardrails:
* Per-tenant rate limit — max 1 broadcast per 5 minutes.
  Second attempt inside window → 429.
* Audience size ceiling — 5000 recipients (hard).  Above → 400
  ``AUDIENCE_TOO_LARGE`` (future work: paginated fanout).
* Idempotency — every send must present a short-lived
  ``confirm_token`` issued by ``/preview``; single-use, 10-minute TTL.
* Admin-only — manager / tech / customer / super_admin-except-tenant
  → 403.  Server is the security boundary; the UI is a hint.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()

# ── Constants ─────────────────────────────────────────────────────
_ADMIN_ROLES = {"admin", "super_admin"}
_AUDIENCE_CAP = 5000
_RATE_LIMIT_WINDOW_SEC = 5 * 60
_CONFIRM_TOKEN_TTL_SEC = 10 * 60


# ── Pydantic bodies ───────────────────────────────────────────────
class BroadcastBase(BaseModel):
    channels: List[str] = Field(..., min_items=1, max_items=2)
    template_id: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    audience: str = Field("all_active_customers")
    # Phase 16 · Item 3 · Feb-2026 — audience filters. All optional
    # arrays; empty (or absent) means "no restriction on that axis".
    # Multiple filters are ANDed. Values inside each array are ORed
    # (any-of semantics).
    category_ids: List[str] = Field(default_factory=list)
    service_days: List[str] = Field(default_factory=list)
    assigned_tech_user_ids: List[str] = Field(default_factory=list)
    # Feb-2026 · Item 2 — audience-status selector.
    # ``active`` (default) | ``inactive`` | ``both``.
    audience_status: str = Field("active", pattern="^(active|inactive|both)$")


class BroadcastPreviewIn(BroadcastBase):
    pass


class BroadcastSendIn(BroadcastBase):
    confirm_token: str = Field(..., min_length=8, max_length=128)


# ── Guards ────────────────────────────────────────────────────────
def _require_admin(user: dict) -> None:
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(403, "Mass messaging is admin-only")


def _validate_channels(channels: List[str]) -> List[str]:
    normalized = [c.strip().lower() for c in (channels or [])]
    if not normalized:
        raise HTTPException(400, "channels must include at least one of email|sms")
    for c in normalized:
        if c not in ("email", "sms"):
            raise HTTPException(400, f"Unknown channel: {c}")
    # de-dupe while preserving order
    seen: set = set()
    out: List[str] = []
    for c in normalized:
        if c not in seen:
            out.append(c); seen.add(c)
    return out


def _validate_audience(audience: str) -> str:
    if audience != "all_active_customers":
        raise HTTPException(400, f"Unsupported audience: {audience}")
    return audience


_VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def _validate_filters(category_ids: List[str], service_days: List[str],
                       assigned_tech_user_ids: List[str]) -> Dict[str, List[str]]:
    """Normalize the three filter arrays. Strips + lowercases days,
    de-dupes each list, drops empties. Rejects unknown day codes with
    400 so the UI can't silently miss them."""
    cats = sorted({(c or "").strip() for c in (category_ids or []) if (c or "").strip()})
    days_low = [(d or "").strip().lower() for d in (service_days or []) if (d or "").strip()]
    for d in days_low:
        if d not in _VALID_DAYS:
            raise HTTPException(400, f"Unknown service_day: {d}")
    days = sorted(set(days_low))
    techs = sorted({(t or "").strip() for t in (assigned_tech_user_ids or []) if (t or "").strip()})
    return {"category_ids": cats, "service_days": days,
             "assigned_tech_user_ids": techs}


# ── Audience resolver ─────────────────────────────────────────────
async def _resolve_audience(tenant_id: str, *,
                              category_ids: Optional[List[str]] = None,
                              service_days: Optional[List[str]] = None,
                              assigned_tech_user_ids: Optional[List[str]] = None,
                              audience_status: str = "active",
                              ) -> List[Dict[str, Any]]:
    """Return customers for a tenant, optionally narrowed by the three
    Phase-16 filters (categories / service days / assigned techs) and
    the Feb-2026 ``audience_status`` selector (``active`` / ``inactive``
    / ``both``, default ``active``).

    Denormalized fields ``customer.category_ids[]`` /
    ``service_days[]`` / ``assigned_tech_ids[]`` are populated by
    ``customer_categories.recompute_customer_denorm`` (idempotent
    boot backfill + on-save hook)."""
    status = (audience_status or "active").lower()
    if status not in ("active", "inactive", "both"):
        status = "active"
    ands = [
        {"$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}]},
    ]
    if status == "active":
        ands.append({"$or": [{"is_active": True}, {"is_active": {"$exists": False}}]})
    elif status == "inactive":
        ands.append({"is_active": False})
    # ``both`` — no status clause. Includes rows with is_active unset.
    q: Dict[str, Any] = {"tenant_id": tenant_id, "$and": ands}
    if category_ids:
        q["category_ids"] = {"$in": category_ids}
    if service_days:
        q["service_days"] = {"$in": service_days}
    if assigned_tech_user_ids:
        q["assigned_tech_ids"] = {"$in": assigned_tech_user_ids}
    return await db.customers.find(q, {"_id": 0}).to_list(_AUDIENCE_CAP + 10)


async def _is_suppressed(tenant_id: str, customer: Dict[str, Any],
                          channel: str) -> bool:
    """Wrap ``marketing_preferences.is_suppressed`` so a broken import
    doesn't take the whole preview down."""
    try:
        from routers.marketing_preferences import is_suppressed
        return bool(await is_suppressed(
            tenant_id, customer, channel=channel, category="marketing"
        ))
    except Exception as exc:  # pragma: no cover
        logger.warning("[mass-messaging] is_suppressed failed: %s", exc)
        return False


# ── Template resolver ─────────────────────────────────────────────
async def _load_template(tenant_id: str, template_id: str,
                          expected_channel: str) -> Dict[str, Any]:
    tpl = await db.marketing_templates.find_one(
        {"id": template_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not tpl:
        raise HTTPException(404, "Template not found")
    tch = (tpl.get("channel") or "").lower()
    if tch and tch != expected_channel:
        raise HTTPException(400,
            f"Template channel mismatch: expected {expected_channel}, got {tch}")
    return tpl


def _pick_subject_body(tpl: Optional[Dict[str, Any]],
                        override_subject: Optional[str],
                        override_body: Optional[str]) -> tuple:
    """Custom subject/body overrides win over a template. Returns
    (subject, body). Either may be empty for SMS (no subject)."""
    subject = override_subject if override_subject is not None else (tpl or {}).get("subject") or ""
    body = override_body if override_body is not None else (tpl or {}).get("body") or ""
    return subject, body


# ── Rate limit ────────────────────────────────────────────────────
async def _enforce_rate_limit(tenant_id: str) -> None:
    """1 broadcast / 5 min / tenant.  Reads the most-recent batch's
    ``started_at`` — no external cache dependency."""
    last = await db.mass_messaging_batches.find_one(
        {"tenant_id": tenant_id},
        {"_id": 0, "started_at": 1},
        sort=[("started_at", -1)],
    )
    if not last:
        return
    started = last.get("started_at")
    if not started:
        return
    try:
        from datetime import datetime, timezone
        s = datetime.fromisoformat(started.replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - s).total_seconds() < _RATE_LIMIT_WINDOW_SEC:
            raise HTTPException(status_code=429, detail={
                "code": "RATE_LIMITED",
                "window_seconds": _RATE_LIMIT_WINDOW_SEC,
                "last_started_at": started,
            })
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        logger.warning("[mass-messaging] rate-limit parse failed: %s", exc)


# ── Confirm-token store ──────────────────────────────────────────
async def _issue_confirm_token(tenant_id: str, user_id: str,
                                channels: List[str], template_id: Optional[str],
                                subject: Optional[str], body: Optional[str],
                                audience: str,
                                filters: Dict[str, List[str]]) -> str:
    tok = new_id()
    await db.mass_messaging_confirm_tokens.insert_one({
        "token": tok,
        "tenant_id": tenant_id,
        "issued_by": user_id,
        "channels": channels,
        "template_id": template_id,
        "subject": subject,
        "body": body,
        "audience": audience,
        # Filters bound to the token — a preview issued for filter set A
        # can't authorize a send for filter set B (same protection
        # already applied to channels + template_id).
        "filters": filters,
        "issued_at": now_iso(),
        "expires_at_epoch": int(time.time()) + _CONFIRM_TOKEN_TTL_SEC,
        "consumed": False,
    })
    return tok


async def _consume_confirm_token(tok: str, tenant_id: str,
                                  channels: List[str], template_id: Optional[str],
                                  subject: Optional[str], body: Optional[str],
                                  audience: str,
                                  filters: Dict[str, List[str]]) -> None:
    """Consume-once semantics via atomic ``find_one_and_update``. The
    stored payload must match the caller's — otherwise a preview for
    audience A can't authorize a send to audience B."""
    row = await db.mass_messaging_confirm_tokens.find_one({"token": tok})
    if not row:
        raise HTTPException(400, {"code": "INVALID_CONFIRM_TOKEN"})
    if row.get("consumed"):
        raise HTTPException(400, {"code": "CONFIRM_TOKEN_ALREADY_USED"})
    if int(row.get("expires_at_epoch") or 0) < int(time.time()):
        raise HTTPException(400, {"code": "CONFIRM_TOKEN_EXPIRED"})
    if row.get("tenant_id") != tenant_id:
        raise HTTPException(400, {"code": "CONFIRM_TOKEN_TENANT_MISMATCH"})
    if sorted(row.get("channels") or []) != sorted(channels):
        raise HTTPException(400, {"code": "CONFIRM_TOKEN_CHANNELS_MISMATCH"})
    if (row.get("template_id") or None) != (template_id or None):
        raise HTTPException(400, {"code": "CONFIRM_TOKEN_TEMPLATE_MISMATCH"})
    if (row.get("audience") or "") != audience:
        raise HTTPException(400, {"code": "CONFIRM_TOKEN_AUDIENCE_MISMATCH"})
    # Phase 16 · Item 3 — bound filters must match. This defends
    # against "preview A → send B" audience swaps just like the
    # channels + template_id guards above.
    stored_filters = row.get("filters") or {}
    for key in ("category_ids", "service_days", "assigned_tech_user_ids"):
        if sorted(stored_filters.get(key) or []) != sorted(filters.get(key) or []):
            raise HTTPException(400, {"code": "CONFIRM_TOKEN_FILTERS_MISMATCH",
                                       "mismatched_field": key})
    # Atomic single-consumer flip.
    upd = await db.mass_messaging_confirm_tokens.find_one_and_update(
        {"token": tok, "consumed": False},
        {"$set": {"consumed": True, "consumed_at": now_iso()}},
    )
    if not upd:
        raise HTTPException(400, {"code": "CONFIRM_TOKEN_ALREADY_USED"})


# ═════════════════════════════════════════════════════════════════
# POST /mass-messaging/preview
# ═════════════════════════════════════════════════════════════════
@router.post("/mass-messaging/preview", tags=["mass-messaging"],
              operation_id="massMessaging.preview")
async def preview_broadcast(
    body: BroadcastPreviewIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    channels = _validate_channels(body.channels)
    audience_key = _validate_audience(body.audience)
    filters = _validate_filters(body.category_ids, body.service_days,
                                  body.assigned_tech_user_ids)

    from services.marketing.render import render_subject_and_body
    from services.marketing.merge_tags import render_context

    # 1. Load template (if any) — must match a channel from the request.
    email_tpl: Optional[Dict[str, Any]] = None
    sms_tpl: Optional[Dict[str, Any]] = None
    if body.template_id:
        tpl = await db.marketing_templates.find_one(
            {"id": body.template_id, "tenant_id": tenant["id"]}, {"_id": 0},
        )
        if not tpl:
            raise HTTPException(404, "Template not found")
        tch = (tpl.get("channel") or "").lower()
        if tch == "email":
            email_tpl = tpl
        elif tch == "sms":
            sms_tpl = tpl
        else:
            raise HTTPException(400,
                f"Template channel unsupported for broadcast: {tch}")

    if not body.template_id and not (body.subject or body.body):
        raise HTTPException(400,
            "Provide either template_id or subject/body")

    # 2. Resolve audience with the Phase-16 filter set applied.
    customers = await _resolve_audience(
        tenant["id"],
        category_ids=filters["category_ids"],
        service_days=filters["service_days"],
        assigned_tech_user_ids=filters["assigned_tech_user_ids"],
        audience_status=getattr(body, "audience_status", "active"),
    )
    if len(customers) > _AUDIENCE_CAP:
        raise HTTPException(400, {
            "code": "AUDIENCE_TOO_LARGE",
            "size": len(customers),
            "cap": _AUDIENCE_CAP,
        })

    # 3. Aggregate stats.
    stats = {
        "audience_size": len(customers),
        "email_eligible": 0, "sms_eligible": 0,
        "no_contact_email": 0, "no_contact_sms": 0,
        "suppressed_email": 0, "suppressed_sms": 0,
    }
    first_email_target: Optional[Dict[str, Any]] = None
    first_sms_target: Optional[Dict[str, Any]] = None

    for c in customers:
        has_email = bool((c.get("email") or "").strip())
        has_phone = bool((c.get("phone") or "").strip())
        if "email" in channels:
            if not has_email:
                stats["no_contact_email"] += 1
            elif await _is_suppressed(tenant["id"], c, "email"):
                stats["suppressed_email"] += 1
            else:
                stats["email_eligible"] += 1
                if first_email_target is None:
                    first_email_target = c
        if "sms" in channels:
            if not has_phone:
                stats["no_contact_sms"] += 1
            elif await _is_suppressed(tenant["id"], c, "sms"):
                stats["suppressed_sms"] += 1
            else:
                stats["sms_eligible"] += 1
                if first_sms_target is None:
                    first_sms_target = c

    # 4. Sample render — pick the first eligible customer for each
    #    channel and render through the canonical engine.
    sample_customer = first_email_target or first_sms_target or (
        customers[0] if customers else {}
    )
    ctx = render_context(customer=sample_customer, tenant=tenant)

    sample_render: Dict[str, Any] = {}
    unresolved: List[str] = []
    if "email" in channels:
        subj, tpl_body = _pick_subject_body(email_tpl, body.subject, body.body)
        s_out, b_out, missing = render_subject_and_body(subj, tpl_body, ctx)
        sample_render["email_subject"] = s_out
        sample_render["email_body_html"] = b_out
        unresolved.extend(missing)
    if "sms" in channels:
        _s, tpl_body = _pick_subject_body(sms_tpl, None, body.body if not email_tpl else body.body)
        # SMS has no subject; if the caller provided one, ignore it.
        s_out, b_out, missing = render_subject_and_body("", tpl_body, ctx)
        # Strip HTML for SMS surface (matches adapter behavior).
        from services.marketing.render import strip_html
        sample_render["sms_body"] = strip_html(b_out)
        unresolved.extend(missing)
    sample_render["unresolved_tokens"] = sorted(set(unresolved))
    sample_render["sample_customer"] = {
        "id": sample_customer.get("id"),
        "name": sample_customer.get("name"),
    }

    # 5. Rough cost hint — Resend + RC are pay-per-send; ballpark $
    #    per unit is stable enough for a ceiling estimate.
    cost = 0.0
    if "email" in channels:
        cost += stats["email_eligible"] * 0.001   # ~$0.001 per email
    if "sms" in channels:
        cost += stats["sms_eligible"] * 0.0075    # ~$0.0075 per SMS

    # 6. Issue confirm token (single-use, 10-min TTL). Filters are
    #    bound so a preview for filter set A can't authorize a send
    #    for filter set B.
    tok = await _issue_confirm_token(
        tenant_id=tenant["id"], user_id=user["id"],
        channels=channels, template_id=body.template_id,
        subject=body.subject, body=body.body, audience=audience_key,
        filters=filters,
    )

    return {
        "estimated_recipients": {
            "email": stats["email_eligible"],
            "sms": stats["sms_eligible"],
        },
        "stats": stats,
        "sample_render": sample_render,
        "estimated_cost_hint": round(cost, 4),
        "confirm_token": tok,
        "audience_cap": _AUDIENCE_CAP,
        "filters_applied": filters,
    }


# ═════════════════════════════════════════════════════════════════
# POST /mass-messaging/send
# ═════════════════════════════════════════════════════════════════
async def _run_broadcast(*, tenant_id: str, batch_id: str,
                          channels: List[str], template_id: Optional[str],
                          subject: Optional[str], body: Optional[str],
                          initiated_by: str,
                          category_ids: Optional[List[str]] = None,
                          service_days: Optional[List[str]] = None,
                          assigned_tech_user_ids: Optional[List[str]] = None,
                          audience_status: str = "active",
                          ) -> None:
    """Background fanout: iterate audience, render, hit the adapter,
    persist a `marketing_deliveries` row per (customer, channel).
    Updates the batch's stats + status when done.

    Structured logging: emits a start line with the resolved recipient
    count and an end line with terminal stats so ops can trace a
    broadcast in server logs even if the caller never polls the
    batch. Every adapter failure is captured into the delivery row's
    `error` field — no silent drops."""
    from services.marketing.render import render_subject_and_body, strip_html
    from services.marketing.merge_tags import render_context
    from services.email.resend_adapter import send as _send_email
    from services.sms.rc_adapter import send as _send_sms

    stats = {"sent": 0, "failed": 0, "suppressed": 0, "no_contact": 0}

    # Reload template(s) — background task may run after a schema hot-reload.
    email_tpl = sms_tpl = None
    if template_id:
        tpl = await db.marketing_templates.find_one(
            {"id": template_id, "tenant_id": tenant_id}, {"_id": 0},
        )
        if tpl:
            tch = (tpl.get("channel") or "").lower()
            if tch == "email":
                email_tpl = tpl
            elif tch == "sms":
                sms_tpl = tpl

    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    customers = await _resolve_audience(
        tenant_id,
        category_ids=category_ids,
        service_days=service_days,
        assigned_tech_user_ids=assigned_tech_user_ids,
        audience_status=audience_status,
    )
    logger.info(
        "[mass-messaging] fanout START batch=%s tenant=%s recipients=%d channels=%s",
        batch_id, tenant_id, len(customers), channels,
    )

    for c in customers:
        ctx = render_context(customer=c, tenant=tenant or {})
        # ── email ─────────────────────────────────────────────
        if "email" in channels:
            addr = (c.get("email") or "").strip()
            if not addr:
                stats["no_contact"] += 1
                await _log_delivery(
                    tenant_id=tenant_id, batch_id=batch_id, customer=c,
                    channel="email", subject=None, body="",
                    status="no_contact", provider="none",
                )
            else:
                subj_tpl, body_tpl = _pick_subject_body(email_tpl, subject, body)
                s_out, b_out, _ = render_subject_and_body(subj_tpl, body_tpl, ctx)
                try:
                    res = await _send_email(
                        to=addr, subject=s_out, html=b_out,
                        category="marketing",
                        tenant_id=tenant_id, customer_id=c.get("id"),
                        idempotency_key=f"mb:{batch_id}:{c.get('id')}:email",
                    )
                    status = _classify_provider_status(res)
                    err = None if status == "sent" else (res or {}).get("error")
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(
                        "[mass-messaging] email adapter raised batch=%s cust=%s: %s",
                        batch_id, c.get("id"), exc,
                    )
                    res = {}
                    status = "failed"
                    err = str(exc)
                stats[status] = stats.get(status, 0) + 1
                await _log_delivery(
                    tenant_id=tenant_id, batch_id=batch_id, customer=c,
                    channel="email", subject=s_out, body=b_out,
                    status=status,
                    provider=(res or {}).get("provider") or "resend",
                    provider_response_id=(res or {}).get("provider_response_id"),
                    error=err,
                )
        # ── sms ───────────────────────────────────────────────
        if "sms" in channels:
            phone = (c.get("phone") or "").strip()
            if not phone:
                stats["no_contact"] += 1
                await _log_delivery(
                    tenant_id=tenant_id, batch_id=batch_id, customer=c,
                    channel="sms", subject=None, body="",
                    status="no_contact", provider="none",
                )
            else:
                _s, body_tpl = _pick_subject_body(sms_tpl, None, body)
                _s_out, b_out, _ = render_subject_and_body("", body_tpl, ctx)
                sms_body = strip_html(b_out)
                try:
                    res = await _send_sms(
                        to=phone, body=sms_body,
                        category="marketing",
                        tenant_id=tenant_id, customer_id=c.get("id"),
                        idempotency_key=f"mb:{batch_id}:{c.get('id')}:sms",
                    )
                    status = _classify_provider_status(res)
                    err = None if status == "sent" else (res or {}).get("error")
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(
                        "[mass-messaging] sms adapter raised batch=%s cust=%s: %s",
                        batch_id, c.get("id"), exc,
                    )
                    res = {}
                    status = "failed"
                    err = str(exc)
                stats[status] = stats.get(status, 0) + 1
                await _log_delivery(
                    tenant_id=tenant_id, batch_id=batch_id, customer=c,
                    channel="sms", subject=None, body=sms_body,
                    status=status,
                    provider=(res or {}).get("provider") or "ringcentral",
                    provider_response_id=(res or {}).get("provider_response_id"),
                    error=err,
                )

    await db.mass_messaging_batches.update_one(
        {"id": batch_id},
        {"$set": {
            "stats": stats,
            "status": "completed",
            "completed_at": now_iso(),
        }},
    )
    logger.info(
        "[mass-messaging] fanout END batch=%s stats=%s",
        batch_id, stats,
    )


def _classify_provider_status(res: Optional[Dict[str, Any]]) -> str:
    """Map an adapter envelope to one of the batch stat buckets:
    ``sent`` | ``suppressed`` | ``failed``.  Mocked mode (no API key)
    counts as ``sent`` — the caller's intent was fulfilled and the
    ledger row still lands.  ``no_contact`` is handled by the caller."""
    ps = (res or {}).get("provider_status") or ""
    if ps in ("sent", "mocked"):
        return "sent"
    if ps == "suppressed":
        return "suppressed"
    return "failed"


async def _log_delivery(*, tenant_id: str, batch_id: str,
                         customer: Dict[str, Any], channel: str,
                         subject: Optional[str], body: str,
                         status: str, provider: str,
                         provider_response_id: Optional[str] = None,
                         error: Optional[str] = None) -> None:
    """One row per (customer, channel) attempt, matching the
    schema every other feature writes (see customers.py:1084).
    Failed sends carry the provider's error message in ``error`` so
    the communications log detail sheet can surface it."""
    recipient = (customer.get("email") if channel == "email"
                  else customer.get("phone")) or ""
    await db.marketing_deliveries.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "customer_id": customer.get("id"),
        "channel": channel,
        "kind": "marketing",
        "recipient": recipient,
        "subject": subject,
        "body": body,
        "trigger_entity": {"kind": "mass_broadcast", "id": batch_id},
        "trigger_id": f"mass_broadcast:{batch_id}",
        "batch_id": batch_id,
        "delivered": status == "sent",
        "delivery_status": status,
        "provider": provider,
        "provider_response_id": provider_response_id,
        "error": error,
        "created_at": now_iso(),
    })


@router.post("/mass-messaging/send", tags=["mass-messaging"],
              operation_id="massMessaging.send")
async def send_broadcast(
    body: BroadcastSendIn,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    channels = _validate_channels(body.channels)
    audience_key = _validate_audience(body.audience)
    filters = _validate_filters(body.category_ids, body.service_days,
                                  body.assigned_tech_user_ids)

    # Rate limit before we consume the confirm token — a stale token
    # shouldn't be burned on a 429.
    await _enforce_rate_limit(tenant["id"])

    # Audience-size guard.
    customers = await _resolve_audience(
        tenant["id"],
        category_ids=filters["category_ids"],
        service_days=filters["service_days"],
        assigned_tech_user_ids=filters["assigned_tech_user_ids"],
        audience_status=getattr(body, "audience_status", "active"),
    )
    if len(customers) > _AUDIENCE_CAP:
        raise HTTPException(400, {
            "code": "AUDIENCE_TOO_LARGE",
            "size": len(customers), "cap": _AUDIENCE_CAP,
        })
    if len(customers) == 0:
        raise HTTPException(400, {
            "code": "AUDIENCE_EMPTY",
            "message": "No active customers to broadcast to.",
        })

    # Consume confirm token — atomic, single-use, tenant-bound.
    await _consume_confirm_token(
        body.confirm_token, tenant["id"], channels, body.template_id,
        body.subject, body.body, audience_key, filters,
    )

    # Estimate queued counts (post-suppression/no-contact).
    queued_email = 0
    queued_sms = 0
    for c in customers:
        if "email" in channels and (c.get("email") or "").strip():
            if not await _is_suppressed(tenant["id"], c, "email"):
                queued_email += 1
        if "sms" in channels and (c.get("phone") or "").strip():
            if not await _is_suppressed(tenant["id"], c, "sms"):
                queued_sms += 1

    # Persist the batch row.
    batch_id = new_id()
    await db.mass_messaging_batches.insert_one({
        "id": batch_id,
        "tenant_id": tenant["id"],
        "initiated_by_user_id": user["id"],
        "channels": channels,
        "template_id": body.template_id,
        "custom_subject": body.subject,
        "custom_body": body.body,
        "audience": audience_key,
        "filters_applied": {
            "audience": audience_key,
            "category_ids": filters["category_ids"],
            "service_days": filters["service_days"],
            "assigned_tech_user_ids": filters["assigned_tech_user_ids"],
        },
        "started_at": now_iso(),
        "completed_at": None,
        "stats": {"sent": 0, "failed": 0, "suppressed": 0,
                   "no_contact": 0},
        "status": "running",
        "queued_email": queued_email,
        "queued_sms": queued_sms,
    })

    # Fanout in background — do not block the HTTP response. Filters
    # are captured on the batch row so the background task can
    # re-resolve the audience identically at fanout time.
    background_tasks.add_task(
        _run_broadcast,
        tenant_id=tenant["id"], batch_id=batch_id, channels=channels,
        template_id=body.template_id, subject=body.subject, body=body.body,
        initiated_by=user["id"],
        category_ids=filters["category_ids"],
        service_days=filters["service_days"],
        assigned_tech_user_ids=filters["assigned_tech_user_ids"],
        audience_status=getattr(body, "audience_status", "active"),
    )

    return {
        "batch_id": batch_id,
        "queued_email": queued_email,
        "queued_sms": queued_sms,
        "status": "running",
    }


# ═════════════════════════════════════════════════════════════════
# GET /mass-messaging/batches
# ═════════════════════════════════════════════════════════════════
@router.get("/mass-messaging/batches", tags=["mass-messaging"],
             operation_id="massMessaging.listBatches")
async def list_batches(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _require_admin(user)
    q = {"tenant_id": tenant["id"]}
    total = await db.mass_messaging_batches.count_documents(q)
    rows = await db.mass_messaging_batches.find(
        q, {"_id": 0}
    ).sort("started_at", -1).skip(offset).limit(limit).to_list(limit)
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


# ═════════════════════════════════════════════════════════════════
# GET /mass-messaging/batches/{batch_id}
# ═════════════════════════════════════════════════════════════════
@router.get("/mass-messaging/batches/{batch_id}", tags=["mass-messaging"],
             operation_id="massMessaging.readBatch")
async def read_batch(
    batch_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    _require_admin(user)
    batch = await db.mass_messaging_batches.find_one(
        {"id": batch_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not batch:
        raise HTTPException(404, "Batch not found")
    d_q = {"tenant_id": tenant["id"], "batch_id": batch_id}
    d_total = await db.marketing_deliveries.count_documents(d_q)
    d_rows = await db.marketing_deliveries.find(
        d_q, {"_id": 0}
    ).sort("created_at", 1).skip(offset).limit(limit).to_list(limit)
    return {
        "batch": batch,
        "deliveries": {
            "total": d_total, "limit": limit, "offset": offset,
            "items": d_rows,
        },
    }
