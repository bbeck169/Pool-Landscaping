"""QuoteIQ Phase Q4 · InstaQuote — Public self-quote portal.

Two surfaces:

* **Admin** (`/api/instaquote/*`, `require_admin`): tenants build their
  branded quote page, review submissions, and convert leads into
  Pipelines deals + Draft Estimates + Marketing subscribers.
* **Public** (`/api/public/instaquote/{slug}/*`, no auth): prospects
  land on a branded quote builder, pick services, add-ons and a
  frequency, and submit a lead. The server recomputes the total from
  the config — client-supplied totals are ignored. Honeypot + IP
  rate-limit guard against spam.

Convert is admin-approved (no auto-create on submit) to prevent
poisoning the Pipelines board / Marketing list with junk leads.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field

from config import db, logger
from utils import require_admin, new_id, now_iso
from routers.tenants import get_current_tenant


router = APIRouter(tags=["InstaQuote"])


# ─── Rate-limit (in-memory, per IP) ────────────────────────────────────

_RL_WINDOW_SECONDS = 10 * 60
_RL_MAX_HITS = 3
_rl_hits: Dict[str, deque] = {}


def _rl_allow(ip: str) -> bool:
    """Return True if the IP has fewer than ``_RL_MAX_HITS`` submissions
    in the last ``_RL_WINDOW_SECONDS``. Records the hit. In-memory —
    process-local, resets on restart. Adequate for spam control; a
    Redis-backed limiter is a follow-up when we scale to multiple
    backend replicas."""
    now = time.time()
    q = _rl_hits.setdefault(ip, deque())
    while q and now - q[0] > _RL_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= _RL_MAX_HITS:
        return False
    q.append(now)
    return True


def _reset_rate_limit() -> None:
    """Test-only helper. Clears every recorded IP hit."""
    _rl_hits.clear()


# ─── Models ────────────────────────────────────────────────────────────

class ServiceIn(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = ""
    base_price_cents: int = Field(..., ge=0)
    unit: str = Field(default="visit",
                        description="visit | month | sqft | gallon | job")
    min_qty: int = Field(default=1, ge=0)
    max_qty: int = Field(default=100, ge=1)
    add_ons_available: Optional[List[str]] = None


class AddOnIn(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = ""
    price_cents: int = Field(..., ge=0)
    applies_to_service_ids: Optional[List[str]] = None


class FrequencyIn(BaseModel):
    id: Optional[str] = None
    label: str = Field(..., min_length=1, max_length=80)
    multiplier: float = Field(..., ge=0)


class RuleIn(BaseModel):
    # ``if.service_id`` + ``if.min_qty`` triggers ``then.apply_addon_id``
    # or ``then.discount_pct``. Kept opaque as a dict — validated only
    # shallowly since the shape is UI-driven.
    if_: Dict[str, Any] = Field(..., alias="if")
    then_: Dict[str, Any] = Field(..., alias="then")

    model_config = {"populate_by_name": True}


class CollectFieldsIn(BaseModel):
    name: bool = True
    email: bool = True
    phone: bool = True
    address: bool = False
    notes: bool = False


class ConfigIn(BaseModel):
    slug: str = Field(..., min_length=2, max_length=80)
    headline: str = Field(default="Get an instant quote.")
    subheadline: Optional[str] = ""
    hero_image_url: Optional[str] = None
    brand_color: Optional[str] = "#0284C7"
    logo_url: Optional[str] = None
    services: List[ServiceIn] = Field(default_factory=list)
    add_ons: List[AddOnIn] = Field(default_factory=list)
    frequencies: List[FrequencyIn] = Field(default_factory=list)
    rules: List[RuleIn] = Field(default_factory=list)
    collect_fields: CollectFieldsIn = Field(default_factory=CollectFieldsIn)
    thank_you_html: Optional[str] = "Thanks — we'll be in touch shortly."
    success_redirect_url: Optional[str] = None
    active: bool = False


class ConfigPatch(BaseModel):
    headline: Optional[str] = None
    subheadline: Optional[str] = None
    hero_image_url: Optional[str] = None
    brand_color: Optional[str] = None
    logo_url: Optional[str] = None
    services: Optional[List[ServiceIn]] = None
    add_ons: Optional[List[AddOnIn]] = None
    frequencies: Optional[List[FrequencyIn]] = None
    rules: Optional[List[RuleIn]] = None
    collect_fields: Optional[CollectFieldsIn] = None
    thank_you_html: Optional[str] = None
    success_redirect_url: Optional[str] = None


class ContactIn(BaseModel):
    name: Optional[str] = ""
    email: Optional[EmailStr] = None
    phone: Optional[str] = ""
    address: Optional[str] = ""
    notes: Optional[str] = ""


class SelectionIn(BaseModel):
    service_id: str
    qty: float = Field(..., ge=0)
    frequency_id: Optional[str] = None
    add_on_ids: List[str] = Field(default_factory=list)
    custom_notes: Optional[str] = ""


class SubmissionIn(BaseModel):
    """Public quote submission body.

    Canonical shape (confirmed post-Q4 tester review):
      * ``selections`` — **array** of ``{service_id, qty, frequency_id,
        add_on_ids[], custom_notes}``. Supports multi-service submissions.
      * ``_hp`` — hidden honeypot input. Any non-empty value causes
        the server to return a real-shaped ack without persisting.
    """
    contact: ContactIn
    selections: List[SelectionIn] = Field(default_factory=list,
        description="Array of service selections (one entry per selected service).")
    # ``_hp`` is the wire alias; the Python attribute is ``hp_field``
    # (pydantic v2 forbids leading-underscore field names).
    hp_field: Optional[str] = Field(default="", alias="_hp",
        description="Honeypot — must remain empty on the wire.")

    model_config = {"populate_by_name": True}


class DismissIn(BaseModel):
    note: Optional[str] = ""


class SubmitAckOut(BaseModel):
    """Canonical response for ``POST /public/instaquote/{slug}/submit``.

    Same shape is returned for the honeypot path — spammers can't
    A/B the response and identify the trap.
    """
    id: str = Field(..., description="Submission id (fabricated on the honeypot path).")
    status: str = Field(..., description="Always ``new`` for the current flow.")
    total_cents: int = Field(..., description="Server-computed total. Client-supplied totals are ignored.")
    thank_you_html: str = Field(..., description="HTML fragment to render after submit.")
    success_redirect_url: Optional[str] = Field(None, description="Optional external URL to redirect to on success.")


# ─── Helpers ───────────────────────────────────────────────────────────

def _clean(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not d:
        return d
    out = dict(d)
    out.pop("_id", None)
    return out


def _normalize_config_lists(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Assign ids to any list entry that arrived without one — keeps
    the config self-consistent across PATCH round-trips."""
    for key in ("services", "add_ons", "frequencies"):
        for item in cfg.get(key) or []:
            if not item.get("id"):
                item["id"] = new_id()
    return cfg


def _public_view(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Non-sensitive projection returned by the public endpoint. Never
    exposes tenant_id, internal timestamps, or activation state."""
    return {
        "slug": cfg.get("slug"),
        "headline": cfg.get("headline") or "",
        "subheadline": cfg.get("subheadline") or "",
        "hero_image_url": cfg.get("hero_image_url"),
        "brand_color": cfg.get("brand_color") or "#0284C7",
        "logo_url": cfg.get("logo_url"),
        "services": cfg.get("services") or [],
        "add_ons": cfg.get("add_ons") or [],
        "frequencies": cfg.get("frequencies") or [],
        "collect_fields": cfg.get("collect_fields") or {},
        "thank_you_html": cfg.get("thank_you_html") or "",
        "success_redirect_url": cfg.get("success_redirect_url"),
    }


def _compute_total(cfg: Dict[str, Any],
                     selections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """SERVER-SIDE total calculation. Client totals are never trusted.
    Returns {total_cents, breakdown:[{service_id, name, qty, unit_price_cents,
    frequency_id, frequency_multiplier, add_ons:[{id,name,price_cents}],
    line_total_cents}]}."""
    services_by_id = {s["id"]: s for s in (cfg.get("services") or [])}
    addons_by_id = {a["id"]: a for a in (cfg.get("add_ons") or [])}
    freq_by_id = {f["id"]: f for f in (cfg.get("frequencies") or [])}
    breakdown: List[Dict[str, Any]] = []
    total = 0
    for sel in selections:
        svc = services_by_id.get(sel.get("service_id"))
        if not svc:
            continue
        qty = float(sel.get("qty") or 0)
        min_q = int(svc.get("min_qty") or 0)
        max_q = int(svc.get("max_qty") or qty)
        # Clamp qty to configured min/max — protects against client
        # tampering with hidden inputs.
        qty = max(min_q, min(max_q, qty))
        if qty <= 0:
            continue
        unit = int(svc.get("base_price_cents") or 0)
        freq = freq_by_id.get(sel.get("frequency_id") or "") or {}
        mult = float(freq.get("multiplier") or 1.0)
        addons_selected: List[Dict[str, Any]] = []
        addons_sum = 0
        allowed_addon_ids = set(svc.get("add_ons_available") or [])
        for aid in sel.get("add_on_ids") or []:
            a = addons_by_id.get(aid)
            if not a:
                continue
            # Only allow add-ons that either apply to this service OR
            # are in the service's `add_ons_available` allow-list.
            applies = a.get("applies_to_service_ids") or []
            if applies and svc["id"] not in applies:
                continue
            if allowed_addon_ids and aid not in allowed_addon_ids:
                continue
            addons_selected.append({
                "id": aid, "name": a.get("name"),
                "price_cents": int(a.get("price_cents") or 0),
            })
            addons_sum += int(a.get("price_cents") or 0)
        line_total = int(round((unit * qty + addons_sum) * mult))
        total += line_total
        breakdown.append({
            "service_id": svc["id"], "service_name": svc.get("name"),
            "qty": qty, "unit_price_cents": unit,
            "frequency_id": freq.get("id"),
            "frequency_label": freq.get("label"),
            "frequency_multiplier": mult,
            "add_ons": addons_selected,
            "line_total_cents": line_total,
            "custom_notes": sel.get("custom_notes") or "",
        })
    # Apply discount rules (only ``then.discount_pct`` supported for
    # totals here — add-on triggers are visual-only in this ship).
    for rule in cfg.get("rules") or []:
        if_ = rule.get("if") or rule.get("if_") or {}
        then_ = rule.get("then") or rule.get("then_") or {}
        svc_id = if_.get("service_id")
        min_qty = float(if_.get("min_qty") or 0)
        if not svc_id:
            continue
        hits = [b for b in breakdown
                 if b["service_id"] == svc_id and b["qty"] >= min_qty]
        if not hits:
            continue
        pct = float(then_.get("discount_pct") or 0)
        if pct > 0:
            total = int(round(total * (1 - pct / 100.0)))
    return {"total_cents": total, "breakdown": breakdown}


async def _fire_automation_event(tenant_id: str, event: str,
                                    payload: Dict[str, Any]) -> None:
    """Fire ``event`` into the automation engine. Never raises — swallowed
    on any adapter failure so the submit path can never 500 because of
    a downstream automation issue."""
    try:
        from services.automation_engine import emit
        await emit(event, payload, tenant_id, entity_kind="instaquote",
                    entity_id=payload.get("submission_id", ""))
    except Exception as e:
        logger.warning(f"[instaquote] automation event {event!r} failed: {e}")


# ═════════════════════════════════════════════════════════════════════
# Admin — Config CRUD
# ═════════════════════════════════════════════════════════════════════

@router.post("/instaquote/rate-limit/reset")
async def reset_rate_limit_endpoint(user: dict = Depends(require_admin)):
    """Ops endpoint — clear the in-memory IP rate-limit counter. Admins
    can call this to unblock a legitimate customer whose office IP got
    flagged. Also used by the test suite (which cannot reach the
    process-local counter otherwise)."""
    _reset_rate_limit()
    return {"ok": True}


@router.get("/instaquote/configs")
async def list_configs(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    rows = await db.instaquote_configs.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return {"count": len(rows), "configs": rows}


@router.post("/instaquote/configs", status_code=201)
async def create_config(body: ConfigIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    slug = (body.slug or "").strip().lower()
    # Slugs are globally unique (public URL keys) — enforce here.
    existing = await db.instaquote_configs.find_one({"slug": slug}, {"_id": 0})
    if existing:
        raise HTTPException(409, "slug already taken")
    now = now_iso()
    doc = _normalize_config_lists({
        "id": new_id(), "tenant_id": tenant["id"], "slug": slug,
        "headline": body.headline, "subheadline": body.subheadline or "",
        "hero_image_url": body.hero_image_url,
        "brand_color": body.brand_color or "#0284C7",
        "logo_url": body.logo_url,
        "services": [s.model_dump() for s in body.services],
        "add_ons": [a.model_dump() for a in body.add_ons],
        "frequencies": [f.model_dump() for f in body.frequencies],
        "rules": [r.model_dump(by_alias=True) for r in body.rules],
        "collect_fields": body.collect_fields.model_dump(),
        "thank_you_html": body.thank_you_html or "",
        "success_redirect_url": body.success_redirect_url,
        "active": bool(body.active),
        "created_at": now, "updated_at": now,
    })
    if doc["active"]:
        # Activate exclusivity: only one active per tenant.
        await db.instaquote_configs.update_many(
            {"tenant_id": tenant["id"]}, {"$set": {"active": False}})
    await db.instaquote_configs.insert_one(doc)
    return _clean(doc)


@router.get("/instaquote/configs/{cid}")
async def get_config(cid: str,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    row = await db.instaquote_configs.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "config not found")
    return row


@router.patch("/instaquote/configs/{cid}")
async def patch_config(cid: str, body: ConfigPatch,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    row = await db.instaquote_configs.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "config not found")
    updates = body.model_dump(exclude_none=True)
    for k in ("services", "add_ons", "frequencies"):
        if k in updates and isinstance(updates[k], list):
            updates[k] = [
                (v.model_dump() if hasattr(v, "model_dump") else v)
                for v in updates[k]
            ]
    if "rules" in updates and isinstance(updates["rules"], list):
        updates["rules"] = [
            (v.model_dump(by_alias=True) if hasattr(v, "model_dump") else v)
            for v in updates["rules"]
        ]
    if "collect_fields" in updates and hasattr(updates["collect_fields"], "model_dump"):
        updates["collect_fields"] = updates["collect_fields"].model_dump()
    updates["updated_at"] = now_iso()
    row.update(updates)
    row = _normalize_config_lists(row)
    await db.instaquote_configs.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": row})
    return _clean(row)


@router.delete("/instaquote/configs/{cid}", status_code=204)
async def delete_config(cid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    r = await db.instaquote_configs.delete_one(
        {"id": cid, "tenant_id": tenant["id"]})
    if not r.deleted_count:
        raise HTTPException(404, "config not found")
    return None


@router.post("/instaquote/configs/{cid}/activate")
async def activate_config(cid: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    row = await db.instaquote_configs.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "config not found")
    await db.instaquote_configs.update_many(
        {"tenant_id": tenant["id"]}, {"$set": {"active": False}})
    await db.instaquote_configs.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"active": True, "updated_at": now_iso()}})
    return {"ok": True, "id": cid}


# ═════════════════════════════════════════════════════════════════════
# Admin — Submissions
# ═════════════════════════════════════════════════════════════════════

@router.get("/instaquote/submissions")
async def list_submissions(user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant),
                             status: Optional[str] = Query(None),
                             limit: int = Query(50, ge=1, le=200),
                             cursor: Optional[str] = Query(None)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status:
        q["status"] = status
    if cursor:
        q["submitted_at"] = {"$lt": cursor}
    rows = await db.instaquote_submissions.find(q, {"_id": 0}) \
        .sort("submitted_at", -1).to_list(limit)
    # Hydrate ``contact_history_count`` — number of prior submissions
    # from the same subscriber (matched by lower-cased email OR
    # normalized phone when email is missing). One aggregate keyed by
    # email/phone → count. Kept per-request rather than persisted so
    # counts stay accurate as the linked subscriber accumulates rows.
    emails = set()
    phones = set()
    for r in rows:
        c = r.get("contact") or {}
        e = (c.get("email") or "").strip().lower()
        if e:
            emails.add(e)
        else:
            p = "".join(ch for ch in (c.get("phone") or "")
                          if ch.isdigit() or ch == "+")
            if p:
                phones.add(p)
    email_counts: Dict[str, int] = {}
    phone_counts: Dict[str, int] = {}
    if emails:
        pipeline = [
            {"$match": {"tenant_id": tenant["id"],
                          "contact.email": {"$in": list(emails)}}},
            {"$group": {"_id": {"$toLower": "$contact.email"},
                          "n": {"$sum": 1}}},
        ]
        async for row in db.instaquote_submissions.aggregate(pipeline):
            email_counts[row["_id"]] = int(row.get("n") or 0)
    if phones:
        pipeline = [
            {"$match": {"tenant_id": tenant["id"],
                          "contact.phone": {"$in": list(phones)}}},
            {"$group": {"_id": "$contact.phone", "n": {"$sum": 1}}},
        ]
        async for row in db.instaquote_submissions.aggregate(pipeline):
            phone_counts[row["_id"]] = int(row.get("n") or 0)
    for r in rows:
        c = r.get("contact") or {}
        e = (c.get("email") or "").strip().lower()
        if e:
            r["contact_history_count"] = email_counts.get(e, 1)
        else:
            p = "".join(ch for ch in (c.get("phone") or "")
                          if ch.isdigit() or ch == "+")
            r["contact_history_count"] = phone_counts.get(p, 1) if p else 1
    return {
        "count": len(rows),
        "submissions": rows,
        "next_cursor": rows[-1]["submitted_at"] if len(rows) == limit else None,
    }


@router.get("/instaquote/submissions/{sid}")
async def get_submission(sid: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    row = await db.instaquote_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "submission not found")
    return row


@router.post("/instaquote/submissions/{sid}/dismiss")
async def dismiss_submission(sid: str, body: DismissIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    row = await db.instaquote_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "submission not found")
    if row.get("status") == "converted":
        raise HTTPException(409, "already converted")
    await db.instaquote_submissions.update_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"$set": {"status": "dismissed",
                   "dismiss_note": body.note or "",
                   "dismissed_at": now_iso(),
                   "dismissed_by": user.get("id")}})
    fresh = await db.instaquote_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    return _clean(fresh)


@router.post("/instaquote/submissions/{sid}/convert")
async def convert_submission(sid: str,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    """Atomically create a Deal + Draft Estimate + Subscriber from an
    InstaQuote submission. If any step fails we roll back the ones that
    already succeeded so the tenant doesn't see a half-converted lead.
    """
    sub = await db.instaquote_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not sub:
        raise HTTPException(404, "submission not found")
    if sub.get("status") == "converted":
        raise HTTPException(409, "already converted")
    # Compact rollback log — we push (collection, filter) tuples as we
    # go and undo on any exception downstream.
    inserted: List[tuple] = []
    try:
        # 1) Deal — into the tenant's default pipeline, "New Lead" (first) stage.
        from routers.pipelines import _ensure_default_pipeline, _log_event
        await _ensure_default_pipeline(tenant["id"])
        pipeline = await db.deal_pipelines.find_one(
            {"tenant_id": tenant["id"], "is_default": True}, {"_id": 0})
        stages = (pipeline or {}).get("stages") or []
        new_lead_stage = next(
            (s for s in stages if (s.get("name") or "").lower().startswith("new")),
            stages[0] if stages else None,
        )
        if not new_lead_stage:
            raise HTTPException(500, "no stages on default pipeline")
        now = now_iso()
        contact = sub.get("contact") or {}
        deal_id = new_id()
        deal_doc = {
            "id": deal_id, "tenant_id": tenant["id"],
            "pipeline_id": pipeline["id"],
            "stage_id": new_lead_stage["id"],
            "title": f"InstaQuote · {contact.get('name') or contact.get('email') or 'lead'}",
            "customer_id": None,
            "contact_name": contact.get("name") or "",
            "contact_email": (contact.get("email") or "").lower() or None,
            "contact_phone": contact.get("phone") or None,
            "value_cents": int(sub.get("computed_total_cents") or 0),
            "probability_pct": int(new_lead_stage.get("probability_pct") or 10),
            "owner_user_id": user.get("id"),
            "tags": ["instaquote"], "notes": contact.get("notes") or "",
            "source": "instaquote", "status": "open",
            "lost_reason": None,
            "created_at": now, "updated_at": now,
            "stage_entered_at": now,
        }
        await db.deals.insert_one(deal_doc)
        inserted.append(("deals", {"id": deal_id}))
        await _log_event(tenant["id"], deal_id, "created",
                          to_value={"stage_id": new_lead_stage["id"],
                                    "stage_name": new_lead_stage.get("name")},
                          actor_user_id=user.get("id"),
                          meta={"source": "instaquote_convert",
                                 "submission_id": sid})

        # 2) Draft Estimate — one line item per breakdown row. Prices
        # are in cents in InstaQuote, but the estimates table stores
        # ``unit_cost`` in dollars — convert.
        line_items = []
        for b in sub.get("computed_breakdown_json") or []:
            unit_dollars = (int(b.get("unit_price_cents") or 0) / 100.0) \
                * float(b.get("frequency_multiplier") or 1.0)
            line_items.append({
                "description": (
                    f"{b.get('service_name') or 'Service'}"
                    + (f" · {b.get('frequency_label')}"
                        if b.get("frequency_label") else "")
                ),
                "quantity": float(b.get("qty") or 0),
                "unit_cost": round(unit_dollars, 2),
            })
            # Roll add-ons into their own line for clarity.
            for a in b.get("add_ons") or []:
                line_items.append({
                    "description": f"Add-on · {a.get('name')}",
                    "quantity": float(b.get("qty") or 1),
                    "unit_cost": round(
                        int(a.get("price_cents") or 0) / 100.0
                        * float(b.get("frequency_multiplier") or 1.0), 2),
                })
        est_id = new_id()
        est_doc = {
            "id": est_id, "tenant_id": tenant["id"],
            "customer_id": None,
            "customer_name": contact.get("name") or "",
            "title": f"InstaQuote · {contact.get('name') or contact.get('email') or 'lead'}",
            "line_items": line_items,
            "overhead_pct": 0.0, "margin_pct": 0.0,
            "notes": contact.get("notes") or "",
            "terms": "", "status": "draft",
            "source": "instaquote",
            "instaquote_submission_id": sid,
            "converted_quote_id": None,
            "created_at": now, "updated_at": now,
        }
        await db.estimates.insert_one(est_doc)
        inserted.append(("estimates", {"id": est_id}))

        # 3) Marketing subscriber (source="instaquote").
        #
        # Matching contract:
        #   1. PRIMARY key = (tenant_id, lower(email))  — case-insensitive.
        #   2. FALLBACK    = (tenant_id, normalized(phone))  — only when
        #      email is missing / not provided at all.
        #   Rationale: two different emails may share a household phone,
        #   so phone match must NOT run when a distinct email is
        #   supplied — otherwise we alias different leads to the same
        #   subscriber (Q4 tester finding).
        # On match:  keep the id, set source=instaquote if missing,
        #            append the current submission_id to
        #            linked_submission_ids (deduped).
        # On miss:   insert a new subscriber with source=instaquote.
        # Defensive: after the write, we re-fetch and assert the
        # returned subscriber's contact matches the submission's.
        sub_id = None
        email = (contact.get("email") or "").strip().lower() or None
        phone_norm = "".join(ch for ch in (contact.get("phone") or "")
                              if ch.isdigit() or ch == "+") or None
        if email or phone_norm:
            existing_sub = None
            if email:
                existing_sub = await db.subscribers.find_one(
                    {"tenant_id": tenant["id"], "email": email}, {"_id": 0})
            elif phone_norm:
                # Only fall back to phone when there is NO email on this
                # submission — never when email is present but happens
                # to miss.
                existing_sub = await db.subscribers.find_one(
                    {"tenant_id": tenant["id"], "phone": phone_norm}, {"_id": 0})
            if existing_sub:
                sub_id = existing_sub["id"]
                linked = list(existing_sub.get("linked_submission_ids") or [])
                if sid not in linked:
                    linked.append(sid)
                update = {
                    "linked_submission_ids": linked,
                    "updated_at": now,
                }
                if not existing_sub.get("source"):
                    update["source"] = "instaquote"
                # Backfill missing email/phone when we matched by the
                # other channel.
                if email and not existing_sub.get("email"):
                    update["email"] = email
                if phone_norm and not existing_sub.get("phone"):
                    update["phone"] = phone_norm
                await db.subscribers.update_one(
                    {"id": sub_id, "tenant_id": tenant["id"]},
                    {"$set": update})
            else:
                sub_id = new_id()
                name_parts = (contact.get("name") or "").split(" ", 1)
                sub_doc = {
                    "id": sub_id, "tenant_id": tenant["id"],
                    "email": email, "phone": phone_norm,
                    "first_name": name_parts[0] if name_parts else "",
                    "last_name": name_parts[1] if len(name_parts) > 1 else "",
                    "status": "subscribed", "source": "instaquote",
                    "customer_id": None, "tags": ["instaquote_lead"],
                    "attributes": {"submission_id": sid},
                    "linked_submission_ids": [sid],
                    "consent_at": now, "confirmed_at": now,
                    "unsubscribed_at": None, "confirmation_token": None,
                    "created_at": now, "updated_at": now,
                }
                await db.subscribers.insert_one(sub_doc)
                inserted.append(("subscribers", {"id": sub_id}))

            # DEFENSIVE POST-CHECK: the subscriber we return MUST have
            # a contact channel that matches this submission. Fails
            # loudly if the upsert accidentally aliased a different
            # lead. Rolls back on mismatch.
            check = await db.subscribers.find_one(
                {"id": sub_id, "tenant_id": tenant["id"]}, {"_id": 0})
            if not check:
                raise HTTPException(500, "subscriber upsert missing after write")
            if email and (check.get("email") or "") != email:
                raise HTTPException(500,
                    f"subscriber email mismatch: expected {email!r}, "
                    f"got {check.get('email')!r}")
            if phone_norm and not email \
                    and (check.get("phone") or "") != phone_norm:
                raise HTTPException(500,
                    f"subscriber phone mismatch: expected {phone_norm!r}, "
                    f"got {check.get('phone')!r}")
    except HTTPException:
        for coll, filt in inserted:
            await db[coll].delete_one(filt)
        raise
    except Exception as e:
        logger.warning(f"[instaquote] convert failed, rolling back: {e}")
        for coll, filt in inserted:
            await db[coll].delete_one(filt)
        raise HTTPException(500, f"convert failed: {e}")

    await db.instaquote_submissions.update_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"$set": {"status": "converted",
                   "converted_at": now,
                   "converted_by": user.get("id"),
                   "converted_deal_id": deal_id,
                   "converted_estimate_id": est_id,
                   "converted_subscriber_id": sub_id}})
    fresh = await db.instaquote_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    return {
        "submission": _clean(fresh),
        "deal_id": deal_id,
        "estimate_id": est_id,
        "subscriber_id": sub_id,
    }


# ═════════════════════════════════════════════════════════════════════
# Public — Config fetch + Submit (NO auth)
# ═════════════════════════════════════════════════════════════════════

@router.get("/public/instaquote/{slug}")
async def public_config(slug: str):
    """Unauthenticated. Returns ONLY non-sensitive fields. Only served
    when the config is active — draft/paused pages 404."""
    row = await db.instaquote_configs.find_one({"slug": slug, "active": True},
                                                   {"_id": 0})
    if not row:
        raise HTTPException(404, "not found")
    return _public_view(row)


@router.post("/public/instaquote/{slug}/submit", status_code=201,
              response_model=SubmitAckOut,
              description=(
                  "Public quote submission endpoint. NO auth.\n\n"
                  "Body shape: `contact` object + `selections` array + "
                  "hidden `_hp` honeypot. `contact` is filtered per the "
                  "tenant's `collect_fields` config on the client, but "
                  "the server accepts any subset.\n\n"
                  "**Server always recomputes the total** from the "
                  "config — client-supplied totals are ignored. "
                  "Qty is clamped to per-service `min_qty` / `max_qty`. "
                  "Add-on selections are filtered against the service's "
                  "allow-list. Discount rules (`if.service_id + min_qty "
                  "→ then.discount_pct`) are applied last.\n\n"
                  "Rate-limit: 3 submissions per IP per 10 min. "
                  "Honeypot: any non-empty `_hp` value causes a real-"
                  "shaped ack without persistence."
              ))
async def public_submit(slug: str, body: SubmissionIn, request: Request):
    row = await db.instaquote_configs.find_one({"slug": slug, "active": True},
                                                   {"_id": 0})
    if not row:
        raise HTTPException(404, "not found")

    # Honeypot: return a REAL-SHAPED ack + the SAME server-computed
    # total_cents a legit submit would have produced. A determined
    # attacker can no longer fingerprint the trap by comparing totals.
    # No persistence, no automation event, no rate-limit slot spent.
    if getattr(body, "hp_field", None):
        hp_selections = [s.model_dump() for s in body.selections]
        hp_computed = _compute_total(row, hp_selections)
        return {
            "id": new_id(),
            "status": "new",
            "total_cents": hp_computed["total_cents"],
            "thank_you_html": row.get("thank_you_html") or "",
            "success_redirect_url": row.get("success_redirect_url"),
        }

    # Rate-limit by IP. Consider X-Forwarded-For (Kubernetes ingress
    # sets it) before falling back to the socket peer.
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() \
        or (request.client.host if request.client else "unknown")
    if not _rl_allow(ip):
        raise HTTPException(429, "rate limit — try again in a few minutes")

    selections = [s.model_dump() for s in body.selections]
    computed = _compute_total(row, selections)
    now = now_iso()
    doc = {
        "id": new_id(), "tenant_id": row["tenant_id"],
        "config_slug": slug,
        "contact": body.contact.model_dump(),
        "selections": selections,
        "computed_total_cents": computed["total_cents"],
        "computed_breakdown_json": computed["breakdown"],
        "status": "new",
        "converted_deal_id": None,
        "converted_estimate_id": None,
        "converted_subscriber_id": None,
        "ip": ip,
        "user_agent": (request.headers.get("user-agent") or "")[:512],
        "referrer": (request.headers.get("referer") or "")[:512],
        "submitted_at": now,
    }
    await db.instaquote_submissions.insert_one(doc)
    doc.pop("_id", None)

    # Fire the automation event — non-fatal on failure.
    await _fire_automation_event(row["tenant_id"], "instaquote.submitted", {
        "submission_id": doc["id"],
        "config_slug": slug,
        "total_cents": computed["total_cents"],
        "contact_email": (body.contact.email or "") if body.contact else "",
        "contact_name": (body.contact.name or "") if body.contact else "",
    })

    # Unified notifications — new_lead ping to tenant admins.
    try:
        from services.notifications import enqueue_for_tenant_admins
        contact = body.contact
        who = (contact.name if contact else "") or (contact.email if contact else "") or "New prospect"
        amount = f"${computed['total_cents'] / 100:,.2f}"
        await enqueue_for_tenant_admins(
            row["tenant_id"], "new_lead",
            title=f"New lead · {who}",
            body=f"InstaQuote submission — {amount}. Slug: {slug}.",
            source_ref={"kind": "instaquote_submission", "id": doc["id"]},
            href=f"/instaquote/submissions/{doc['id']}",
            priority="high",
        )
    except Exception as _e:
        logger.warning(f"[instaquote] unified notify failed: {_e}")

    # Public response is minimal — no tenant leak, no breakdown echo.
    return {
        "id": doc["id"],
        "status": "new",
        "total_cents": doc["computed_total_cents"],
        "thank_you_html": row.get("thank_you_html") or "",
        "success_redirect_url": row.get("success_redirect_url"),
    }
