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

router = APIRouter()


ALLOWED_CHANNELS = {"email", "sms"}
ALLOWED_CATEGORIES = {
    "service_completed", "invoice_sent", "past_due",
    "welcome", "review_request", "general",
}


class TemplateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    channel: str
    category: str = "general"
    subject: Optional[str] = None
    body: str = ""
    active: bool = True


class TemplatePatch(BaseModel):
    name: Optional[str] = None
    channel: Optional[str] = None
    category: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
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


# ═══════════════════════════════════════════════════════════════════════
# Static-path routes FIRST — declared before ``{tid}`` capture below.
# ═══════════════════════════════════════════════════════════════════════
@router.get("/marketing/templates/variables")
async def list_variables(user: dict = Depends(require_admin)):
    """Return the registry of supported Mustache variables so the UI
    can render an insert-variable dropdown."""
    return {"variables": VARIABLES_REGISTRY}


@router.get("/marketing/templates")
async def list_templates(
    channel: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if channel:
        q["channel"] = channel
    if category:
        q["category"] = category
    if active is not None:
        q["active"] = active
    rows = await db.marketing_templates.find(q, {"_id": 0}).sort(
        [("system", -1), ("updated_at", -1)],
    ).to_list(500)
    return {"templates": rows, "count": len(rows)}


@router.post("/marketing/templates", status_code=201)
async def create_template(
    body: TemplateIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    _validate_shape(body.channel, body.subject)
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "name": body.name.strip(),
        "channel": body.channel,
        "category": body.category or "general",
        "subject": (body.subject or "").strip() if body.channel == "email" else None,
        "body": body.body or "",
        "active": bool(body.active),
        "system": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user.get("id"),
    }
    await db.marketing_templates.insert_one(doc)
    return _serialize(doc)


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

    subject_rendered, body_rendered, missing = render_subject_and_body(
        row.get("subject") or "",
        row.get("body") or "",
        ctx,
    )
    # SMS strips any HTML that leaked in from a copy-paste — email
    # keeps it verbatim (email clients render inline HTML).
    if row.get("channel") == "sms":
        body_rendered = strip_html(body_rendered)

    return {
        "subject_rendered": subject_rendered if row.get("channel") == "email" else None,
        "body_rendered": body_rendered,
        "missing_vars": sorted(set(missing)),
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
