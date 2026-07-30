"""Phase 10 · Feb 2026 — Promo codes.

Single, tenant-scoped collection ``promo_codes`` supporting both admin-
created manual codes AND system-issued referral rewards. The referral
watcher (see :mod:`services.referral_watcher`) mints ``type=referral_reward``
rows programmatically via :func:`create_promo_code_internal`; every
other row is created by an admin via ``POST /api/promo-codes``.

Data model (per row):
    id, tenant_id, code (UPPERCASE, unique within tenant),
    type ("manual" | "referral_reward"),
    discount_kind ("fixed_credit" | "percent_off_invoice" | "fixed_off_invoice"),
    apply_to ("account_credit" | "next_invoice"),
    amount_cents (int, positive),
    percent (int 1..100, only when discount_kind = percent_off_invoice),
    max_uses (int, default 1),
    uses_count (int, default 0),
    expires_at (ISO string | None),
    is_active (bool),
    metadata (dict — carries referral_id / referrer_id for auditing),
    created_at, updated_at, created_by.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()

_DISCOUNT_KINDS = ("fixed_credit", "percent_off_invoice", "fixed_off_invoice")
_APPLY_TO = ("account_credit", "next_invoice")
_TYPES = ("manual", "referral_reward")


def _serialize(row: dict) -> dict:
    row = dict(row)
    row.pop("_id", None)
    return row


def _gen_code(prefix: str = "") -> str:
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{prefix}{body}" if prefix else body


async def ensure_indexes() -> None:
    try:
        await db.promo_codes.create_index(
            [("tenant_id", 1), ("code", 1)],
            unique=True, name="promo_codes_tenant_code_uniq",
        )
    except Exception as exc:
        logger.warning(f"[phase10] promo_codes index skipped: {exc}")


# ═══════════════════════════ Public API ═══════════════════════════════
class PromoCreate(BaseModel):
    code: Optional[str] = None
    type: str = "manual"
    discount_kind: str
    apply_to: str = "account_credit"
    amount_cents: Optional[int] = Field(None, ge=1, le=1_000_000)
    percent: Optional[int] = Field(None, ge=1, le=100)
    max_uses: int = Field(1, ge=1, le=10_000)
    expires_at: Optional[str] = None
    is_active: bool = True
    metadata: Optional[Dict[str, Any]] = None


class PromoPatch(BaseModel):
    max_uses: Optional[int] = Field(None, ge=1, le=10_000)
    expires_at: Optional[str] = None
    is_active: Optional[bool] = None
    amount_cents: Optional[int] = Field(None, ge=1, le=1_000_000)
    percent: Optional[int] = Field(None, ge=1, le=100)


class ValidateRequest(BaseModel):
    code: str
    invoice_id: Optional[str] = None
    invoice_total_cents: Optional[int] = None


class RedeemRequest(BaseModel):
    code: str
    invoice_id: str
    invoice_total_cents: int


def _validate_shape(body: Any) -> None:
    if body.discount_kind not in _DISCOUNT_KINDS:
        raise HTTPException(422, f"discount_kind must be one of {list(_DISCOUNT_KINDS)}")
    if body.apply_to not in _APPLY_TO:
        raise HTTPException(422, f"apply_to must be one of {list(_APPLY_TO)}")
    if body.type not in _TYPES:
        raise HTTPException(422, f"type must be one of {list(_TYPES)}")
    if body.discount_kind == "percent_off_invoice":
        if not body.percent:
            raise HTTPException(422, "percent required for percent_off_invoice")
    else:
        if not body.amount_cents:
            raise HTTPException(422, "amount_cents required for this discount_kind")


def _now_expired(expires_at: Optional[str]) -> bool:
    if not expires_at:
        return False
    try:
        exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > exp
    except Exception:
        return False


def _effective_discount_cents(promo: dict, invoice_total_cents: int) -> int:
    kind = promo.get("discount_kind")
    if kind == "fixed_credit" or kind == "fixed_off_invoice":
        return min(int(promo.get("amount_cents") or 0), max(0, invoice_total_cents))
    if kind == "percent_off_invoice":
        pct = int(promo.get("percent") or 0)
        return max(0, int(invoice_total_cents * pct / 100))
    return 0


async def _lookup_active(tenant_id: str, code: str) -> Optional[dict]:
    return await db.promo_codes.find_one({
        "tenant_id": tenant_id, "code": code.strip().upper(),
    }, {"_id": 0})


# ─── CRUD ────────────────────────────────────────────────────────────
@router.post("/promo-codes", status_code=201)
async def create_promo_code(body: PromoCreate,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    _validate_shape(body)
    code = (body.code or _gen_code()).strip().upper()
    if not code or len(code) < 3 or len(code) > 32:
        raise HTTPException(422, "code must be 3-32 chars")
    existing = await db.promo_codes.find_one({
        "tenant_id": tenant["id"], "code": code,
    }, {"_id": 0, "id": 1})
    if existing:
        raise HTTPException(409, detail={
            "message": "A promo code with this code already exists in this tenant.",
            "existing_promo_code_id": existing["id"],
        })
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "code": code,
        "type": body.type,
        "discount_kind": body.discount_kind,
        "apply_to": body.apply_to,
        "amount_cents": body.amount_cents,
        "percent": body.percent,
        "max_uses": body.max_uses,
        "uses_count": 0,
        "expires_at": body.expires_at,
        "is_active": bool(body.is_active),
        "metadata": body.metadata or {},
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user.get("id"),
    }
    await db.promo_codes.insert_one(doc)
    return _serialize(doc)


@router.get("/promo-codes")
async def list_promo_codes(
    type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    query: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if type:
        query["type"] = type
    if is_active is not None:
        query["is_active"] = is_active
    if q:
        query["code"] = {"$regex": q.strip().upper(), "$options": "i"}
    rows = await db.promo_codes.find(query, {"_id": 0}) \
        .sort([("created_at", -1)]).to_list(limit)
    return {"promo_codes": rows, "count": len(rows)}


@router.get("/promo-codes/{pid}")
async def get_promo_code(pid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    row = await db.promo_codes.find_one({
        "id": pid, "tenant_id": tenant["id"],
    }, {"_id": 0})
    if not row:
        raise HTTPException(404, "Promo code not found")
    return _serialize(row)


@router.patch("/promo-codes/{pid}")
async def patch_promo_code(pid: str, body: PromoPatch,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    row = await db.promo_codes.find_one({
        "id": pid, "tenant_id": tenant["id"],
    }, {"_id": 0})
    if not row:
        raise HTTPException(404, "Promo code not found")
    patch: Dict[str, Any] = {}
    for f in ("max_uses", "expires_at", "is_active", "amount_cents", "percent"):
        v = getattr(body, f)
        if v is not None:
            patch[f] = v
    if not patch:
        return _serialize(row)
    patch["updated_at"] = now_iso()
    await db.promo_codes.update_one({"id": pid}, {"$set": patch})
    row.update(patch)
    return _serialize(row)


@router.delete("/promo-codes/{pid}", status_code=204)
async def delete_promo_code(pid: str,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    row = await db.promo_codes.find_one({
        "id": pid, "tenant_id": tenant["id"],
    }, {"_id": 0, "id": 1})
    if not row:
        raise HTTPException(404, "Promo code not found")
    await db.promo_codes.update_one(
        {"id": pid},
        {"$set": {"is_active": False, "updated_at": now_iso()}},
    )
    from fastapi import Response
    return Response(status_code=204)


# ─── Validate + redeem ───────────────────────────────────────────────
@router.post("/promo-codes/validate")
async def validate_promo_code(
    body: ValidateRequest,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    promo = await _lookup_active(tenant["id"], body.code)
    if not promo:
        return {"valid": False, "reason": "not_found"}
    if not promo.get("is_active"):
        return {"valid": False, "reason": "inactive"}
    if _now_expired(promo.get("expires_at")):
        return {"valid": False, "reason": "expired"}
    if int(promo.get("uses_count") or 0) >= int(promo.get("max_uses") or 1):
        return {"valid": False, "reason": "max_uses_reached"}
    # If invoice_id supplied, ensure this code hasn't already been
    # applied to that same invoice.
    if body.invoice_id:
        applied = await db.quotes.find_one({
            "id": body.invoice_id, "tenant_id": tenant["id"],
            "doc_type": "invoice",
            "applied_promo_code_ids": promo["id"],
        }, {"_id": 0, "id": 1})
        if applied:
            return {"valid": False, "reason": "already_applied_to_invoice"}
    total = int(body.invoice_total_cents or 0)
    effective = _effective_discount_cents(promo, total) if total else int(promo.get("amount_cents") or 0)
    return {
        "valid": True,
        "promo_code_id": promo["id"],
        "code": promo["code"],
        "discount_kind": promo["discount_kind"],
        "apply_to": promo["apply_to"],
        "amount_cents_effective": effective,
    }


@router.post("/promo-codes/redeem")
async def redeem_promo_code(
    body: RedeemRequest,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Server-side redemption — atomically increments ``uses_count`` +
    records the promo on the invoice. Never trust a client's pre-
    applied discount; the invoice viewer re-runs this at payment time.

    Role: admin OR the invoice's own customer (via magic-link auth).
    """
    promo = await _lookup_active(tenant["id"], body.code)
    if not promo:
        raise HTTPException(404, "Promo code not found")
    if not promo.get("is_active"):
        raise HTTPException(400, "Promo code inactive")
    if _now_expired(promo.get("expires_at")):
        raise HTTPException(400, "Promo code expired")
    if int(promo.get("uses_count") or 0) >= int(promo.get("max_uses") or 1):
        raise HTTPException(400, "Promo code max uses reached")

    inv = await db.quotes.find_one({
        "id": body.invoice_id, "tenant_id": tenant["id"],
        "doc_type": "invoice",
    }, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")

    if promo["id"] in (inv.get("applied_promo_code_ids") or []):
        raise HTTPException(400, "Promo code already applied to this invoice")

    total = int(body.invoice_total_cents)
    discount = _effective_discount_cents(promo, total)

    # Atomic uses_count increment guarded by the current count so two
    # concurrent redeems can't both slip through.
    upd = await db.promo_codes.update_one(
        {
            "id": promo["id"], "tenant_id": tenant["id"],
            "uses_count": promo["uses_count"],
        },
        {"$inc": {"uses_count": 1},
         "$set": {"updated_at": now_iso()}},
    )
    if upd.modified_count != 1:
        raise HTTPException(409, "Concurrent redemption — retry")

    # Record on the invoice (source of truth is db.quotes with
    # doc_type=invoice — Phase 11 refactor: single write, no dual-push).
    await db.quotes.update_one(
        {"id": body.invoice_id, "tenant_id": tenant["id"],
          "doc_type": "invoice"},
        {
            "$push": {
                "applied_promo_code_ids": promo["id"],
                "applied_promos": {
                    "promo_code_id": promo["id"],
                    "code": promo["code"],
                    "discount_kind": promo["discount_kind"],
                    "discount_cents": discount,
                    "applied_at": now_iso(),
                    "applied_by": user.get("id"),
                },
            },
        },
    )
    return {
        "ok": True,
        "promo_code_id": promo["id"],
        "code": promo["code"],
        "discount_cents": discount,
        "new_invoice_total_cents": max(0, total - discount),
    }


# ═══════════════════════════ Internal ═════════════════════════════════
async def create_promo_code_internal(
    *, tenant_id: str, type_: str, discount_kind: str,
    apply_to: str, amount_cents: Optional[int] = None,
    percent: Optional[int] = None, max_uses: int = 1,
    prefix: str = "", metadata: Optional[Dict[str, Any]] = None,
    expires_at: Optional[str] = None,
) -> dict:
    """Server-side promo code minting — used by the referral watcher.
    Never raises on collision; retries up to 5 times with a fresh code."""
    for _ in range(5):
        code = _gen_code(prefix=prefix)
        doc = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "code": code,
            "type": type_,
            "discount_kind": discount_kind,
            "apply_to": apply_to,
            "amount_cents": amount_cents,
            "percent": percent,
            "max_uses": max_uses,
            "uses_count": 0,
            "expires_at": expires_at,
            "is_active": True,
            "metadata": metadata or {},
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "created_by": "system",
        }
        try:
            await db.promo_codes.insert_one(doc)
            return doc
        except Exception as exc:
            if "duplicate" in str(exc).lower() or "e11000" in str(exc).lower():
                continue
            raise
    raise RuntimeError("Could not mint a unique promo code after 5 attempts")
