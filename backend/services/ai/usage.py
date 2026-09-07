"""Phase I1.7.c.1 · Feb-2026 — AI usage tracking + monthly cap enforcement.

Two Mongo collections:

  ``tenant_ai_provider``
      Sidecar metadata (``monthly_token_cap``, ``default_model``)
      stored in plaintext so cap-checks avoid decrypting secrets on
      every call. The API key itself lives encrypted in
      ``tenant_secrets`` under ``provider_key = "ai_<short>"``.

  ``tenant_ai_usage``
      One row per ``(tenant_id, provider_short, period_yyyymm)``.
      Tokens are ``$inc``'d atomically after each successful call.

Cap semantics (locked by user 2026-02):
  * ``monthly_token_cap = None``  → UNLIMITED (default).
  * ``monthly_token_cap = 0``      → BLOCK ALL (explicit kill-switch).
  * ``monthly_token_cap > 0``      → hard block at ``used >= cap``,
                                      soft warn at ``used >= 0.8 * cap``.
  * Cap is checked against ``tokens_total`` (prompt + completion),
    NOT per-field.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._helpers import current_period_yyyymm, now_iso
from .models import TenantAIUsageCapExceeded


PROVIDER_META_COLLECTION = "tenant_ai_provider"
USAGE_COLLECTION = "tenant_ai_usage"

SOFT_WARN_RATIO = 0.8


def _default_db():
    from config import db
    return db


# ── Provider metadata (cap + default_model) ─────────────────────
async def upsert_provider_meta(
    *, tenant_id: str, provider: str,
    monthly_token_cap: Optional[int] = None,
    default_model: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """Idempotent upsert of the ``tenant_ai_provider`` sidecar row.
    ``monthly_token_cap`` semantics: ``None`` = unlimited,
    ``0`` = block all, ``>0`` = enforce."""
    if db is None:
        db = _default_db()
    set_fields: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "provider": provider,
        "monthly_token_cap": monthly_token_cap,
        "default_model": default_model,
        "updated_at": now_iso(),
    }
    await db[PROVIDER_META_COLLECTION].update_one(
        {"tenant_id": tenant_id, "provider": provider},
        {"$set": set_fields, "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )
    return set_fields


async def get_provider_meta(
    *, tenant_id: str, provider: str, db=None,
) -> Optional[Dict[str, Any]]:
    if db is None:
        db = _default_db()
    return await db[PROVIDER_META_COLLECTION].find_one(
        {"tenant_id": tenant_id, "provider": provider},
        {"_id": 0},
    )


async def remove_provider_meta(
    *, tenant_id: str, provider: str, db=None,
) -> bool:
    if db is None:
        db = _default_db()
    res = await db[PROVIDER_META_COLLECTION].delete_one(
        {"tenant_id": tenant_id, "provider": provider}
    )
    return res.deleted_count > 0


# ── Usage tracking ───────────────────────────────────────────────
async def record_usage(
    *, tenant_id: str, provider: str,
    tokens_prompt: int, tokens_completion: int,
    period_yyyymm: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """Atomically increment the tenant's monthly token counters."""
    if db is None:
        db = _default_db()
    period = period_yyyymm or current_period_yyyymm()
    total = int(tokens_prompt) + int(tokens_completion)
    await db[USAGE_COLLECTION].update_one(
        {"tenant_id": tenant_id, "provider": provider, "period_yyyymm": period},
        {
            "$inc": {
                "tokens_prompt": int(tokens_prompt),
                "tokens_completion": int(tokens_completion),
                "tokens_total": total,
            },
            "$set": {"updated_at": now_iso()},
            "$setOnInsert": {"created_at": now_iso()},
        },
        upsert=True,
    )
    row = await db[USAGE_COLLECTION].find_one(
        {"tenant_id": tenant_id, "provider": provider, "period_yyyymm": period},
        {"_id": 0},
    )
    return row or {}


async def get_usage_row(
    *, tenant_id: str, provider: str,
    period_yyyymm: Optional[str] = None,
    db=None,
) -> Optional[Dict[str, Any]]:
    if db is None:
        db = _default_db()
    period = period_yyyymm or current_period_yyyymm()
    return await db[USAGE_COLLECTION].find_one(
        {"tenant_id": tenant_id, "provider": provider, "period_yyyymm": period},
        {"_id": 0},
    )


async def get_all_usage_rows(
    *, tenant_id: str,
    period_yyyymm: Optional[str] = None,
    db=None,
) -> List[Dict[str, Any]]:
    if db is None:
        db = _default_db()
    period = period_yyyymm or current_period_yyyymm()
    out: List[Dict[str, Any]] = []
    async for row in db[USAGE_COLLECTION].find(
        {"tenant_id": tenant_id, "period_yyyymm": period},
        {"_id": 0},
    ):
        out.append(row)
    return out


# ── Cap enforcement ──────────────────────────────────────────────
def _compute_status(*, used: int, cap: Optional[int]) -> str:
    """Return ``"ok"|"warn"|"blocked"`` for a (used, cap) pair.

    Cap semantics: ``None`` = unlimited → always ``ok``.
    ``0`` = block all → always ``blocked``.
    ``>0`` → ``blocked`` when ``used >= cap`` else ``warn`` when
    ``used >= 0.8*cap`` else ``ok``.
    """
    if cap is None:
        return "ok"
    if cap <= 0:
        return "blocked"
    if used >= cap:
        return "blocked"
    if used >= int(cap * SOFT_WARN_RATIO):
        return "warn"
    return "ok"


async def enforce_cap_or_raise(
    *, tenant_id: str, provider: str, db=None,
) -> Dict[str, Any]:
    """Raise ``TenantAIUsageCapExceeded`` when the tenant has already
    hit their monthly cap. Returns a snapshot dict with current
    ``used``/``cap``/``status`` on the ok/warn path so callers can
    surface soft warnings to the client.
    """
    meta = await get_provider_meta(tenant_id=tenant_id, provider=provider, db=db)
    cap: Optional[int] = None
    if meta is not None:
        raw_cap = meta.get("monthly_token_cap")
        cap = int(raw_cap) if raw_cap is not None else None
    row = await get_usage_row(tenant_id=tenant_id, provider=provider, db=db)
    used = int((row or {}).get("tokens_total", 0) or 0)
    status = _compute_status(used=used, cap=cap)
    if status == "blocked":
        raise TenantAIUsageCapExceeded(provider=provider, cap=int(cap or 0), used=used)
    return {"used": used, "cap": cap, "status": status}
