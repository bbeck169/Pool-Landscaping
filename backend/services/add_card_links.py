"""Phase 12 · Feb 2026 — "Require card on file" magic-link plumbing.

* ``encode_add_card_token(customer_id, tenant_id, ttl_days=30)`` →
  short JWT usable by the public ``/portal/add-card`` page.
* ``decode_add_card_token(token)`` → validated ``{customer_id,
  tenant_id, exp}`` dict. Raises ``HTTPException(401, ...)`` on any
  failure (bad signature, expired, wrong sub).
* ``build_add_card_link(base_url, customer_id, tenant_id)`` → full URL
  the customer clicks.
* ``ensure_rate_limit(customer_id)`` → raises 429 if the same customer
  was pinged less than ``_RATE_WINDOW_SECONDS`` ago. In-memory single
  process cache — the worker pool is 1 uvicorn worker in this deploy,
  so a shared cache is unnecessary for the 1/5min spec.
* ``seed_add_card_templates_all_tenants()`` idempotently seeds the
  ``add_card_request_email`` and ``add_card_request_sms`` templates
  on any tenant missing them.

All template bodies use the Phase 9 ``{{TAG}}`` merge-tag syntax and
are rendered by ``services.marketing.merge_tags.render_template`` when
sent. Never inline-substitute at call sites — always route through
``render_template()``.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import jwt
from fastapi import HTTPException

from config import db, logger
from utils import now_iso, new_id

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGO = "HS256"
_TOKEN_SUB = "add_card"

_RATE_WINDOW_SECONDS = 300  # 5 minutes
_RATE_CACHE: Dict[str, float] = {}


# ─── JWT helpers ──────────────────────────────────────────────────────
def encode_add_card_token(customer_id: str, tenant_id: str, *,
                            ttl_days: int = 30) -> str:
    payload = {
        "sub": _TOKEN_SUB,
        "customer_id": customer_id,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=ttl_days),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_add_card_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Link expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid link")
    if payload.get("sub") != _TOKEN_SUB:
        raise HTTPException(status_code=401, detail="Wrong token type")
    if not payload.get("customer_id") or not payload.get("tenant_id"):
        raise HTTPException(status_code=401, detail="Malformed token")
    return payload


def build_add_card_link(base_url: str, customer_id: str,
                          tenant_id: str) -> str:
    """Public URL that lands on the SetupIntent page. ``base_url`` is
    the tenant-visible origin (e.g. ``https://poolscape.example``)."""
    tok = encode_add_card_token(customer_id, tenant_id)
    return f"{base_url.rstrip('/')}/portal/add-card?token={tok}"


# ─── Rate limit (1 per 5 min per customer) ────────────────────────────
def ensure_rate_limit(customer_id: str) -> None:
    now = time.time()
    last = _RATE_CACHE.get(customer_id)
    if last and (now - last) < _RATE_WINDOW_SECONDS:
        remaining = int(_RATE_WINDOW_SECONDS - (now - last))
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED",
                     "retry_after_seconds": remaining},
        )
    _RATE_CACHE[customer_id] = now


def reset_rate_limit(customer_id: str) -> None:
    """Test-only helper — clears the in-memory rate window."""
    _RATE_CACHE.pop(customer_id, None)


# ─── Seed default templates ──────────────────────────────────────────
_EMAIL_SUBJECT = "Please add a card to your account"
_EMAIL_BODY = (
    "<p>Hi {{CUSTOMER_FIRST_NAME}},</p>"
    "<p>To keep your service on schedule, please add a card on file "
    "with {{COMPANY_NAME}}.</p>"
    "<p>Adding a card is quick, secure, and only takes a minute:</p>"
    "<p><a href=\"{{ADD_CARD_LINK}}\">Add my card securely</a></p>"
    "<p>If you have any questions, just reply to this email.</p>"
    "<p>— The {{COMPANY_NAME}} team</p>"
)
_SMS_BODY = (
    "Hi {{CUSTOMER_FIRST_NAME}} — {{COMPANY_NAME}} needs a card on "
    "file for your account. Add it here: {{ADD_CARD_LINK}}"
)

# ─── Batch 12C · Feb 2026 — ambiguous-match digest templates ─────────
_AMBIG_EMAIL_SUBJECT = (
    "[{{COMPANY_NAME}}] {{AMBIGUOUS_MATCH_COUNT}} Stripe customer "
    "matches need review"
)
_AMBIG_EMAIL_BODY = (
    "<p>The weekly Stripe cross-reference sync for "
    "<b>{{COMPANY_NAME}}</b> surfaced "
    "<b>{{AMBIGUOUS_MATCH_COUNT}}</b> ambiguous customer match(es) — "
    "each one has multiple Stripe customer records with the same "
    "email.</p>"
    "<p>Sample: {{AMBIGUOUS_MATCH_SAMPLE}}</p>"
    "<p>Open the resolver in the CRM to pick the correct Stripe "
    "record for each:</p>"
    "<p><a href=\"{{ADD_CARD_LINK}}\">Review ambiguous matches</a></p>"
    "<p style=\"color:#64748B;font-size:12px;margin-top:16px;\">"
    "This alert only fires when the count is greater than zero. "
    "Silent syncs stay silent.</p>"
)
_AMBIG_SMS_BODY = (
    "{{COMPANY_NAME}}: Stripe sync flagged {{AMBIGUOUS_MATCH_COUNT}} "
    "ambiguous customer match(es). Review: {{ADD_CARD_LINK}}"
)


async def seed_add_card_templates_for_tenant(tenant_id: str) -> int:
    """Insert the two ``add_card_request_*`` templates for ``tenant_id``
    if they don't already exist. Batch 12C also seeds the
    ``stripe_sync_ambiguous_matches`` digest template. Returns count
    of rows inserted."""
    inserted = 0
    common = {
        "tenant_id": tenant_id,
        "kind": "transactional",
        "is_system": True,
        "is_active": True,
        "created_at": now_iso(),
    }
    if not await db.marketing_templates.find_one(
        {"tenant_id": tenant_id, "code": "add_card_request_email"}, {"_id": 0}
    ):
        await db.marketing_templates.insert_one({
            **common,
            "id": new_id(), "code": "add_card_request_email",
            "channel": "email", "name": "Add Card — Email Request",
            "subject": _EMAIL_SUBJECT, "body": _EMAIL_BODY,
        })
        inserted += 1
    if not await db.marketing_templates.find_one(
        {"tenant_id": tenant_id, "code": "add_card_request_sms"}, {"_id": 0}
    ):
        await db.marketing_templates.insert_one({
            **common,
            "id": new_id(), "code": "add_card_request_sms",
            "channel": "sms", "name": "Add Card — SMS Request",
            "subject": None, "body": _SMS_BODY,
        })
        inserted += 1
    # Batch 12C · Feb 2026 — ambiguous-match digest templates.
    if not await db.marketing_templates.find_one(
        {"tenant_id": tenant_id, "code": "stripe_sync_ambiguous_matches"},
        {"_id": 0},
    ):
        await db.marketing_templates.insert_one({
            **common,
            "id": new_id(), "code": "stripe_sync_ambiguous_matches",
            "channel": "email",
            "name": "Stripe Sync — Ambiguous Matches Digest",
            "subject": _AMBIG_EMAIL_SUBJECT, "body": _AMBIG_EMAIL_BODY,
        })
        inserted += 1
    if not await db.marketing_templates.find_one(
        {"tenant_id": tenant_id, "code": "stripe_sync_ambiguous_matches_sms"},
        {"_id": 0},
    ):
        await db.marketing_templates.insert_one({
            **common,
            "id": new_id(), "code": "stripe_sync_ambiguous_matches_sms",
            "channel": "sms",
            "name": "Stripe Sync — Ambiguous Matches SMS",
            "subject": None, "body": _AMBIG_SMS_BODY,
        })
        inserted += 1
    return inserted


async def seed_add_card_templates_all_tenants() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        try:
            counts[t["id"]] = await seed_add_card_templates_for_tenant(t["id"])
        except Exception as exc:
            logger.warning(f"[phase12] add-card template seed failed for "
                            f"tenant {t.get('id')}: {exc}")
            counts[t["id"]] = 0
    return counts


async def ensure_require_card_default_on_tenants() -> int:
    """Boot migration — set ``require_card_on_file_default: true`` on
    every tenant that doesn't have the field yet. Idempotent."""
    res = await db.tenants.update_many(
        {"require_card_on_file_default": {"$exists": False}},
        {"$set": {"require_card_on_file_default": True}},
    )
    return int(res.modified_count or 0)


async def ensure_tenants_timezone_backfill() -> dict:
    """Batch 12C · Feb 2026 — idempotent timezone audit.

    Iterates every tenant. For each with ``timezone`` missing OR empty,
    sets ``timezone="America/Phoenix"`` (the pod-wide fallback used by
    the Phase 12B weekly cron + Phase 11 tracker digest).

    Returns ``{"audited": N, "filled": M}`` for the boot summary log.
    """
    audited = 0
    filled = 0
    async for t in db.tenants.find(
        {}, {"_id": 0, "id": 1, "timezone": 1},
    ):
        audited += 1
        current = (t.get("timezone") or "").strip()
        if not current:
            await db.tenants.update_one(
                {"id": t["id"]},
                {"$set": {"timezone": "America/Phoenix",
                            "updated_at": now_iso()}},
            )
            filled += 1
    logger.info(f"[phase12c-tz] audited={audited} filled={filled}")
    return {"audited": audited, "filled": filled}
