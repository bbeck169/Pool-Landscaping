"""Phase 17 · Feb-2026 — QBO OAuth 2.0 + at-rest token encryption.

Design decisions:
* Tokens are Fernet-encrypted at rest. The Fernet key is derived from
  ``JWT_SECRET`` (falls back to ``SECRET_KEY``) via HKDF-SHA256 so no
  new env var is needed. The derived key is deterministic — the same
  process boot will decrypt tokens written by the previous boot.
* OAuth ``state`` is a signed JWT containing ``tenant_id`` + ``nonce`` +
  10-minute TTL. Signed with the same ``JWT_SECRET`` so state
  verification is symmetric with the app's other JWTs.
* ``intuit-oauth`` package (v1.2.7) drives the Intuit-side handshake.
"""

from __future__ import annotations

import base64
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
import jwt as pyjwt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from config import db

logger = logging.getLogger("qbo.oauth")


# ── Fernet key derivation ────────────────────────────────────────────
_SECRET = (
    os.environ.get("JWT_SECRET")
    or os.environ.get("SECRET_KEY")
    or "pool-crm-dev-secret-do-not-use-in-prod"
)


def _fernet() -> Fernet:
    """Derive a per-process Fernet key from the app secret via HKDF."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"qbo.fernet.salt.v1",
        info=b"qbo-oauth-token-encryption",
    )
    key = hkdf.derive(_SECRET.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(s: str) -> str:
    return _fernet().encrypt(s.encode("utf-8")).decode("ascii")


def decrypt(cipher: str) -> str:
    try:
        return _fernet().decrypt(cipher.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(f"failed to decrypt qbo token: {exc}") from exc


# ── Env helpers ──────────────────────────────────────────────────────
def _env() -> Dict[str, str]:
    return {
        "environment": (os.environ.get("QBO_ENVIRONMENT") or "sandbox").strip().lower(),
        "client_id": (os.environ.get("QBO_CLIENT_ID") or "").strip(),
        "client_secret": (os.environ.get("QBO_CLIENT_SECRET") or "").strip(),
        "redirect_uri": (os.environ.get("QBO_REDIRECT_URI") or "").strip(),
        "api_minor": (os.environ.get("QBO_API_MINOR_VERSION") or "65").strip(),
    }


def is_configured() -> bool:
    e = _env()
    return bool(e["client_id"] and e["client_secret"] and e["redirect_uri"])


# ── State JWT ────────────────────────────────────────────────────────
def _sign_state(tenant_id: str) -> str:
    payload = {
        "tenant_id": tenant_id,
        "nonce": uuid.uuid4().hex,
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,  # 10 minutes
        "scope": "qbo_oauth_state",
    }
    return pyjwt.encode(payload, _SECRET, algorithm="HS256")


def _verify_state(state: str) -> Dict[str, Any]:
    return pyjwt.decode(state, _SECRET, algorithms=["HS256"])


# ── Public helpers ───────────────────────────────────────────────────
def build_auth_url(tenant_id: str) -> Dict[str, str]:
    """Return ``{auth_url, state}`` for the connect flow."""
    if not is_configured():
        raise ValueError("qbo_not_configured")

    e = _env()
    state = _sign_state(tenant_id)
    base = "https://appcenter.intuit.com/connect/oauth2"
    params = {
        "client_id": e["client_id"],
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "redirect_uri": e["redirect_uri"],
        "state": state,
    }
    qs = "&".join(f"{k}={_pct(v)}" for k, v in params.items())
    return {"auth_url": f"{base}?{qs}", "state": state}


def _pct(v: str) -> str:
    from urllib.parse import quote
    return quote(v, safe="")


async def handle_callback(
    *, code: str, realm_id: str, state: str, user_id: str,
    _http: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Exchange the auth code for tokens + persist the connection.

    Returns ``{qbo_connection_id, qbo_realm_id, company_name}``.
    """
    if not is_configured():
        raise ValueError("qbo_not_configured")

    try:
        claims = _verify_state(state)
    except pyjwt.PyJWTError as exc:
        raise ValueError(f"invalid_state: {exc}") from exc
    tenant_id = claims.get("tenant_id")
    if not tenant_id:
        raise ValueError("invalid_state_no_tenant")

    e = _env()
    tok_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    basic = base64.b64encode(
        f"{e['client_id']}:{e['client_secret']}".encode("utf-8")
    ).decode("ascii")

    close_client = _http is None
    client = _http or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.post(
            tok_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": e["redirect_uri"],
            },
            headers={
                "Authorization": f"Basic {basic}",
                "Accept": "application/json",
            },
        )
        if resp.status_code >= 400:
            raise ValueError(f"token_exchange_failed:{resp.status_code}:{resp.text[:200]}")
        payload = resp.json()
    finally:
        if close_client:
            await client.aclose()

    now = datetime.now(timezone.utc)
    access = payload["access_token"]
    refresh = payload["refresh_token"]
    access_exp = int(payload.get("expires_in") or 3600)
    refresh_exp = int(payload.get("x_refresh_token_expires_in") or 8640000)

    # Company name is optional — best-effort probe (skip in tests via _http stub).
    company_name = await _probe_company_name(access, realm_id, e, client_factory=lambda: httpx.AsyncClient(timeout=10))

    conn_id = str(uuid.uuid4())
    doc = {
        "id": conn_id,
        "qbo_connection_id": conn_id,
        "tenant_id": tenant_id,
        "qbo_realm_id": str(realm_id),
        "qbo_company_name": company_name,
        "encrypted_access_token": encrypt(access),
        "encrypted_refresh_token": encrypt(refresh),
        "access_token_expires_at": (now + _seconds(access_exp)).isoformat(),
        "refresh_token_expires_at": (now + _seconds(refresh_exp)).isoformat(),
        "environment": e["environment"],
        "status": "active",
        "connected_by": user_id,
        "connected_at": now.isoformat(),
    }
    # Soft-close any prior active connection for the same realm (unique-ish).
    await db.qbo_connections.update_many(
        {"tenant_id": tenant_id, "qbo_realm_id": str(realm_id), "status": "active"},
        {"$set": {"status": "revoked", "revoked_at": now.isoformat(),
                   "revoked_by": user_id}},
    )
    await db.qbo_connections.insert_one(doc)
    return {
        "qbo_connection_id": conn_id,
        "qbo_realm_id": str(realm_id),
        "company_name": company_name,
    }


def _seconds(n: int):
    from datetime import timedelta
    return timedelta(seconds=int(n))


async def _probe_company_name(
    access_token: str, realm_id: str, e: Dict[str, str],
    *, client_factory,
) -> str:
    """Best-effort company-name lookup; failures return empty string."""
    try:
        base = _base_for_env(e["environment"])
        url = f"{base}/v3/company/{realm_id}/companyinfo/{realm_id}"
        async with client_factory() as client:
            r = await client.get(
                url,
                params={"minorversion": e["api_minor"]},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
        if r.status_code >= 400:
            return ""
        return ((r.json() or {}).get("CompanyInfo") or {}).get("CompanyName") or ""
    except Exception:  # noqa: BLE001
        return ""


def _base_for_env(env: str) -> str:
    return (
        "https://sandbox-quickbooks.api.intuit.com"
        if env == "sandbox"
        else "https://quickbooks.api.intuit.com"
    )


async def refresh_access_token(
    qbo_connection_id: str,
    *, _http: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Refresh the access token via Intuit. On 401 → flip connection to
    ``reauth_required`` and return ``{ok: False, error: "reauth_required"}``.
    """
    if not is_configured():
        return {"ok": False, "error": "qbo_not_configured"}
    conn = await db.qbo_connections.find_one(
        {"qbo_connection_id": qbo_connection_id, "status": "active"}, {"_id": 0}
    )
    if not conn:
        return {"ok": False, "error": "connection_not_found"}
    e = _env()
    basic = base64.b64encode(
        f"{e['client_id']}:{e['client_secret']}".encode("utf-8")
    ).decode("ascii")
    refresh_plain = decrypt(conn["encrypted_refresh_token"])

    close_client = _http is None
    client = _http or httpx.AsyncClient(timeout=15)
    try:
        r = await client.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            data={"grant_type": "refresh_token", "refresh_token": refresh_plain},
            headers={
                "Authorization": f"Basic {basic}",
                "Accept": "application/json",
            },
        )
    finally:
        if close_client:
            await client.aclose()

    if r.status_code == 401:
        await db.qbo_connections.update_one(
            {"qbo_connection_id": qbo_connection_id},
            {"$set": {"status": "reauth_required"}},
        )
        return {"ok": False, "error": "reauth_required"}
    if r.status_code >= 400:
        return {"ok": False, "error": f"refresh_failed:{r.status_code}"}

    payload = r.json()
    now = datetime.now(timezone.utc)
    new_access = payload["access_token"]
    new_refresh = payload.get("refresh_token") or refresh_plain
    upd = {
        "encrypted_access_token": encrypt(new_access),
        "encrypted_refresh_token": encrypt(new_refresh),
        "access_token_expires_at": (now + _seconds(int(payload.get("expires_in") or 3600))).isoformat(),
    }
    if payload.get("x_refresh_token_expires_in"):
        upd["refresh_token_expires_at"] = (
            now + _seconds(int(payload["x_refresh_token_expires_in"]))
        ).isoformat()
    await db.qbo_connections.update_one(
        {"qbo_connection_id": qbo_connection_id}, {"$set": upd}
    )
    return {"ok": True, "access_token": new_access}


async def revoke_connection(
    qbo_connection_id: str, *, user_id: str,
    _http: Optional[httpx.AsyncClient] = None,
) -> bool:
    conn = await db.qbo_connections.find_one(
        {"qbo_connection_id": qbo_connection_id}, {"_id": 0}
    )
    if not conn:
        return False
    if is_configured():
        e = _env()
        basic = base64.b64encode(
            f"{e['client_id']}:{e['client_secret']}".encode("utf-8")
        ).decode("ascii")
        try:
            refresh_plain = decrypt(conn["encrypted_refresh_token"])
            close_client = _http is None
            client = _http or httpx.AsyncClient(timeout=10)
            try:
                await client.post(
                    "https://developer.api.intuit.com/v2/oauth2/tokens/revoke",
                    json={"token": refresh_plain},
                    headers={
                        "Authorization": f"Basic {basic}",
                        "Accept": "application/json",
                    },
                )
            finally:
                if close_client:
                    await client.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[qbo.revoke] intuit call failed: %s", exc)
    await db.qbo_connections.update_one(
        {"qbo_connection_id": qbo_connection_id},
        {"$set": {
            "status": "revoked",
            "revoked_at": datetime.now(timezone.utc).isoformat(),
            "revoked_by": user_id,
        }},
    )
    return True


async def get_active_access_token(qbo_connection_id: str) -> Optional[str]:
    """Return a fresh access token for the connection, refreshing if
    needed. Returns None when the connection is invalid / needs reauth."""
    conn = await db.qbo_connections.find_one(
        {"qbo_connection_id": qbo_connection_id, "status": "active"}, {"_id": 0}
    )
    if not conn:
        return None
    try:
        exp = datetime.fromisoformat(conn["access_token_expires_at"])
    except Exception:
        exp = datetime.now(timezone.utc)
    if exp <= datetime.now(timezone.utc):
        r = await refresh_access_token(qbo_connection_id)
        if not r.get("ok"):
            return None
        return r["access_token"]
    return decrypt(conn["encrypted_access_token"])
