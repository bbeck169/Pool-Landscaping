"""Sep-2026 · Per-tenant BYO DataForSEO credentials.

Endpoints (all admin-gated, tenant-scoped):

* ``GET    /api/tenants/me/integrations/dataforseo``  — masked read.
* ``PUT    /api/tenants/me/integrations/dataforseo``  — encrypt + store.
* ``DELETE /api/tenants/me/integrations/dataforseo``  — clear.
* ``POST   /api/tenants/me/integrations/dataforseo/test`` — canary
  DFS call, stamps ``last_verified_at``. Rate-limited 5/hour/tenant.

Design contract:
  • Plaintext never touches the database. Every write goes through
    :func:`services.tenant_secrets_crypto.encrypt_tenant_secret`.
  • Plaintext never leaves the backend. GET responses show a
    masked login only (``abc***@example.com``).
  • ``TENANT_SECRETS_ENC_KEY`` missing → PUT/test return HTTP 503
    with an ops hint. GET + DELETE keep working (feature-flagged
    gracefully).
  • Rate-limit uses an in-memory bucket per tenant (5/hour). Same
    primitive as SP1's signup rate-limit — restart resets, which is
    acceptable for this low-value endpoint (a brute-force oracle
    against a decrypt path is toothless anyway).
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict, EmailStr

from config import db
from routers.tenants import get_current_tenant
from utils import now_iso, require_admin
from services import dataforseo_client as _dfs
from services.tenant_secrets_crypto import (
    encrypt_tenant_secret,
    is_available as _crypto_available,
)


logger = logging.getLogger("tenant_dataforseo_integration")
router = APIRouter(tags=["tenant-integrations"])


# ── In-memory rate limit (5/hr/tenant) ────────────────────────────
_TEST_RL_CAP = 5
_TEST_RL_WINDOW = 3600  # seconds
_test_rl_buckets: Dict[str, list] = {}


def _rate_limit_test(tenant_id: str) -> None:
    now = time.time()
    hist = _test_rl_buckets.setdefault(tenant_id, [])
    _test_rl_buckets[tenant_id] = [t for t in hist if now - t < _TEST_RL_WINDOW]
    if len(_test_rl_buckets[tenant_id]) >= _TEST_RL_CAP:
        raise HTTPException(429, {
            "code": "rate_limited",
            "hint": f"Test endpoint limited to {_TEST_RL_CAP} runs per hour.",
        })
    _test_rl_buckets[tenant_id].append(now)


def _reset_rate_limit_for_tests():
    """Test hook — invoked by pytest fixtures to zero the bucket."""
    _test_rl_buckets.clear()


# ── Payload models ────────────────────────────────────────────────
class DataForSEOPutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: EmailStr = Field(..., description="DFS account email.")
    password: str = Field(..., min_length=6, max_length=256)


class DataForSEOReadOut(BaseModel):
    configured: bool
    configured_at: Optional[str] = None
    configured_by: Optional[str] = None
    last_verified_at: Optional[str] = None
    login_masked: Optional[str] = None


# ── Masking helper ────────────────────────────────────────────────
def _mask_login(login: str) -> str:
    """``brian@plofv.com`` → ``bri***@plofv.com``. Short local
    parts (<3 chars) mask entirely."""
    s = (login or "").strip()
    if "@" not in s:
        return "***"
    local, _, domain = s.partition("@")
    if len(local) <= 3:
        return f"***@{domain}"
    return f"{local[:3]}***@{domain}"


def _read_integ(tenant: Dict[str, Any]) -> Dict[str, Any]:
    return ((tenant.get("settings") or {}).get("integrations") or {}) \
        .get("dataforseo") or {}


def _to_read_out(integ: Dict[str, Any]) -> DataForSEOReadOut:
    configured = bool(integ.get("login_encrypted") and integ.get("password_encrypted"))
    login_masked = None
    if configured:
        # Decrypt just to compute the masked view. If the key is
        # missing, ``decrypt_tenant_secret`` returns None → we
        # still show ``configured=True`` but ``login_masked=None``
        # so the UI can render a "Encryption disabled — cannot
        # display masked value" hint.
        from services.tenant_secrets_crypto import decrypt_tenant_secret
        pt = decrypt_tenant_secret(integ.get("login_encrypted"))
        if pt:
            login_masked = _mask_login(pt)
    return DataForSEOReadOut(
        configured=configured,
        configured_at=integ.get("configured_at"),
        configured_by=integ.get("configured_by"),
        last_verified_at=integ.get("last_verified_at"),
        login_masked=login_masked,
    )


# ── GET (masked) ──────────────────────────────────────────────────
@router.get("/tenants/me/integrations/dataforseo",
             response_model=DataForSEOReadOut)
async def get_dataforseo_integration(
    user: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    return _to_read_out(_read_integ(tenant))


# ── PUT (encrypt + store) ─────────────────────────────────────────
@router.put("/tenants/me/integrations/dataforseo",
             response_model=DataForSEOReadOut)
async def put_dataforseo_integration(
    body: DataForSEOPutIn,
    user: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    if not _crypto_available():
        raise HTTPException(503, {
            "code": "encryption_disabled",
            "hint": "TENANT_SECRETS_ENC_KEY is not configured. Ops "
                       "must set the env var before per-tenant DFS "
                       "credentials can be stored.",
        })
    try:
        login_ct = encrypt_tenant_secret(body.login)
        pw_ct = encrypt_tenant_secret(body.password)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, {
            "code": "encryption_failed", "hint": str(exc),
        })
    now = now_iso()
    upd = {
        "settings.integrations.dataforseo.login_encrypted":    login_ct,
        "settings.integrations.dataforseo.password_encrypted": pw_ct,
        "settings.integrations.dataforseo.configured_at":      now,
        "settings.integrations.dataforseo.configured_by":      user["id"],
    }
    await db.tenants.update_one({"id": tenant["id"]}, {"$set": upd})
    # Audit trail — never log ciphertext.
    logger.info(
        "[dfs-tenant-integ] PUT tenant=%s admin=%s login_masked=%s",
        tenant["id"], user["id"], _mask_login(body.login),
    )
    fresh = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0})
    return _to_read_out(_read_integ(fresh or {}))


# ── DELETE (clear) ────────────────────────────────────────────────
@router.delete("/tenants/me/integrations/dataforseo",
                response_model=DataForSEOReadOut)
async def delete_dataforseo_integration(
    user: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$unset": {
            "settings.integrations.dataforseo.login_encrypted":    "",
            "settings.integrations.dataforseo.password_encrypted": "",
            "settings.integrations.dataforseo.configured_at":      "",
            "settings.integrations.dataforseo.configured_by":      "",
            "settings.integrations.dataforseo.last_verified_at":   "",
        }},
    )
    logger.info("[dfs-tenant-integ] DELETE tenant=%s admin=%s",
                  tenant["id"], user["id"])
    return DataForSEOReadOut(configured=False)


# ── POST /test (canary) ───────────────────────────────────────────
class DataForSEOTestOut(BaseModel):
    ok: bool
    latency_ms: int
    error: Optional[str] = None
    last_verified_at: Optional[str] = None
    source: Optional[str] = None  # "tenant" always for this endpoint


@router.post("/tenants/me/integrations/dataforseo/test",
              response_model=DataForSEOTestOut)
async def test_dataforseo_integration(
    user: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _rate_limit_test(tenant["id"])
    integ = _read_integ(tenant)
    if not (integ.get("login_encrypted") and integ.get("password_encrypted")):
        raise HTTPException(400, {
            "code": "not_configured",
            "hint": "PUT credentials first before testing the connection.",
        })
    creds = _dfs.get_credentials_for_tenant(tenant)
    if creds is None:
        # Decrypt failed — either key missing or ciphertext tampered.
        return DataForSEOTestOut(
            ok=False, latency_ms=0,
            error="decrypt_failed_or_key_missing",
            source="tenant",
        )
    t0 = time.time()
    status, body, err = await _dfs.serp_google_organic_live(
        "connectivity test", 33.4484, -112.0740,
        creds_override=creds,
    )
    latency_ms = int((time.time() - t0) * 1000)
    if err:
        logger.warning(
            "[dfs-tenant-integ] test FAIL tenant=%s err=%s latency_ms=%d",
            tenant["id"], err, latency_ms,
        )
        return DataForSEOTestOut(ok=False, latency_ms=latency_ms,
                                    error=err, source="tenant")
    now = now_iso()
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"settings.integrations.dataforseo.last_verified_at": now}},
    )
    logger.info(
        "[dfs-tenant-integ] test OK tenant=%s latency_ms=%d",
        tenant["id"], latency_ms,
    )
    return DataForSEOTestOut(ok=True, latency_ms=latency_ms,
                                last_verified_at=now, source="tenant")
