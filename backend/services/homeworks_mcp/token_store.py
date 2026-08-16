"""Feb-2026 · Homeworks OAuth token store (Fernet-at-rest).

Persists the ``access_token`` + ``refresh_token`` returned by the
Homeworks ``/oauth/token`` endpoint. Both tokens are Fernet-encrypted
before insertion; the Fernet key is HKDF-derived from ``JWT_SECRET``
(or ``SECRET_KEY``) the same way :mod:`services.qbo.oauth` does, so
this module needs zero new env vars and shares the "prod operators
set JWT_SECRET explicitly" contract.

Collection shape (``homeworks_oauth_tokens``)::

    {
      tenant_id:                 str,   # unique index
      encrypted_access_token:    str,   # Fernet(base64)
      encrypted_refresh_token:   str,
      expires_at:                datetime,
      scope:                     str,   # "openid company"
      connected_by_user_id:      str,
      connected_by_user_email:   str,   # denormalised for the status card
      connected_at:              datetime,
      updated_at:                datetime,
    }
"""
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from config import db

logger = logging.getLogger("homeworks_mcp.token_store")

_SECRET = (
    os.environ.get("JWT_SECRET")
    or os.environ.get("SECRET_KEY")
    or "pool-crm-dev-secret-do-not-use-in-prod"
)

# Distinct HKDF salt from QBO so a leaked QBO key can't decrypt Homeworks
# tokens and vice-versa.
_FERNET_SALT = b"homeworks.mcp.fernet.salt.v1"


def _fernet() -> Fernet:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_FERNET_SALT,
        info=b"homeworks-mcp-oauth-token-encryption",
    )
    key = hkdf.derive(_SECRET.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(cipher: str) -> str:
    try:
        return _fernet().decrypt(cipher.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(f"failed to decrypt homeworks token: {exc}") from exc


_indexes_ensured = False


async def ensure_indexes() -> None:
    """Create the unique ``tenant_id`` index. Idempotent."""
    global _indexes_ensured
    if _indexes_ensured:
        return
    try:
        await db.homeworks_oauth_tokens.create_index(
            "tenant_id", unique=True
        )
        _indexes_ensured = True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[homeworks_oauth] tokens ensure_indexes noop: %s", exc,
        )


async def upsert_tokens(
    *,
    tenant_id: str,
    access_token: str,
    refresh_token: str,
    expires_in_secs: int,
    scope: str,
    user_id: str,
    user_email: Optional[str],
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    doc: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "encrypted_access_token": encrypt(access_token),
        "encrypted_refresh_token": encrypt(refresh_token),
        "expires_at": now + timedelta(seconds=int(expires_in_secs)),
        "scope": scope,
        "connected_by_user_id": user_id,
        "connected_by_user_email": user_email or "",
        "connected_at": now,
        "updated_at": now,
    }
    await ensure_indexes()
    await db.homeworks_oauth_tokens.replace_one(
        {"tenant_id": tenant_id}, doc, upsert=True
    )
    return doc


async def update_after_refresh(
    *,
    tenant_id: str,
    access_token: str,
    refresh_token: Optional[str],
    expires_in_secs: int,
) -> None:
    """Rotate the stored access token (and optionally refresh token).

    Homeworks MAY issue a new refresh token on each refresh call
    (rotation). When it does, replace the stored value; when it
    doesn't, keep the original.
    """
    now = datetime.now(timezone.utc)
    upd: Dict[str, Any] = {
        "encrypted_access_token": encrypt(access_token),
        "expires_at": now + timedelta(seconds=int(expires_in_secs)),
        "updated_at": now,
    }
    if refresh_token:
        upd["encrypted_refresh_token"] = encrypt(refresh_token)
    await db.homeworks_oauth_tokens.update_one(
        {"tenant_id": tenant_id}, {"$set": upd}
    )


async def get_by_tenant(tenant_id: str) -> Optional[Dict[str, Any]]:
    doc = await db.homeworks_oauth_tokens.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}
    )
    return doc


async def delete_by_tenant(tenant_id: str) -> int:
    r = await db.homeworks_oauth_tokens.delete_one({"tenant_id": tenant_id})
    return int(getattr(r, "deleted_count", 0) or 0)


def status_view(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Public-facing subset of the doc (no cipher text). Used by the
    ``GET /status`` route + the debug refresh route."""
    if not doc:
        return {
            "connected": False,
            "connected_by_email": None,
            "connected_at": None,
            "expires_at": None,
            "scope": None,
        }
    def _iso(v: Any) -> Optional[str]:
        if isinstance(v, datetime):
            return v.isoformat()
        return v if isinstance(v, str) else None
    return {
        "connected": True,
        "connected_by_email": doc.get("connected_by_user_email") or None,
        "connected_at": _iso(doc.get("connected_at")),
        "expires_at": _iso(doc.get("expires_at")),
        "scope": doc.get("scope"),
    }
