"""Phase I1.7.a · Feb-2026 — TenantSecret store (encrypted at rest).

High-level API::

    put_secret(tenant_id, provider_key, plaintext, *, connection_type,
               connected_account_id=None) -> None
    get_secret(tenant_id, provider_key) -> Optional[str]
    remove_secret(tenant_id, provider_key) -> bool
    list_connections(tenant_id) -> List[ConnectionSummary]
    connection_summary(tenant_id, provider_key) -> Optional[ConnectionSummary]

Contract
--------
* ``put_secret`` is *idempotent by (tenant_id, provider_key)*:
  writing a second value for the same tuple ROTATES the record —
  new IV, new ciphertext, ``updated_at`` bumped. The prior plaintext
  is unrecoverable after a successful rotate (the old DEK+ciphertext
  is overwritten atomically inside a single Mongo upsert).
* ``get_secret`` is the ONLY path that returns plaintext, and only
  to callers inside the encryption boundary (provider adapters).
* ``list_connections`` NEVER returns plaintext. The response
  includes ``last_4`` + status flags only.
* Every ``get_secret`` bumps ``last_used_at`` (fire-and-forget) so
  operators can spot stale credentials in the UI.
* ``log_error`` appends a compact error entry (capped at 20) so the
  UI can surface the most recent connection failure without leaking
  the payload.

Motor-friendly: each function accepts an optional ``db=`` kwarg so
tests can inject a per-event-loop handle. Default resolves to the
process-wide ``config.db``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from .crypto import EncryptedRecord, decrypt, encrypt, last_4
from .models import (
    ConnectionStatus,
    ConnectionSummary,
    ConnectionType,
)


COLLECTION = "tenant_secrets"
_ERROR_LOG_CAP = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_db():
    from config import db  # local import so .env has time to load
    return db


def _mask_account_id(acct: Optional[str]) -> Optional[str]:
    if not acct:
        return None
    if len(acct) <= 8:
        return acct
    # e.g. "acct_1AB…9xyz" — first 5 chars + ellipsis + last 4.
    return f"{acct[:5]}…{acct[-4:]}"


def _summary_from_row(row: dict) -> ConnectionSummary:
    err_log = row.get("error_log") or []
    return ConnectionSummary(
        provider_key=row["provider_key"],
        connection_type=ConnectionType(row["connection_type"]),
        connected=(row.get("connected_status") == ConnectionStatus.CONNECTED.value),
        last_4=row.get("last_4") or None,
        connected_account_id_masked=_mask_account_id(row.get("connected_account_id")),
        last_used_at=row.get("last_used_at"),
        connected_status=ConnectionStatus(row.get("connected_status", "disconnected")),
        error_log_count=len(err_log),
        last_error=(err_log[-1] if err_log else None),
    )


# ── Public API ───────────────────────────────────────────────────
async def put_secret(
    tenant_id: str,
    provider_key: str,
    plaintext: str,
    *,
    connection_type: ConnectionType,
    connected_account_id: Optional[str] = None,
    mask_source: Optional[str] = None,
    db=None,
) -> None:
    """Encrypt ``plaintext`` and upsert the row keyed on
    ``(tenant_id, provider_key)``. Never returns plaintext.

    ``mask_source`` is the string whose last-4 chars are stored in
    the ``last_4`` display field. Defaults to the full ``plaintext``
    — correct for legacy single-string secrets (e.g. Stripe access
    tokens) but useless for JSON-blob configs where the last 4 chars
    are ``"}``. Multi-field messaging providers pass their PRIMARY
    secret field's value here so the UI shows a meaningful tail
    (I1.7.b.fix)."""
    if not isinstance(plaintext, str) or not plaintext:
        raise ValueError("plaintext must be a non-empty str")
    if db is None:
        db = _default_db()

    enc = encrypt(plaintext)
    now = _now_iso()
    existing = await db[COLLECTION].find_one(
        {"tenant_id": tenant_id, "provider_key": provider_key},
        {"id": 1, "created_at": 1},
    )
    # I1.7.b.fix: prefer mask_source when provided; else fall back
    # to plaintext for legacy single-string secrets.
    _mask_from = mask_source if (isinstance(mask_source, str) and mask_source) else plaintext
    doc = {
        "tenant_id": tenant_id,
        "provider_key": provider_key,
        "connection_type": connection_type.value,
        "encrypted_blob": enc.encrypted_blob,
        "iv": enc.iv,
        "auth_tag": enc.auth_tag,
        "dek_wrapped": enc.dek_wrapped,
        "last_4": last_4(_mask_from),
        "connected_status": ConnectionStatus.CONNECTED.value,
        "connected_account_id": connected_account_id,
        "updated_at": now,
    }
    if existing:
        doc["id"] = existing["id"]
        doc["created_at"] = existing.get("created_at", now)
        await db[COLLECTION].replace_one({"id": existing["id"]}, doc)
    else:
        doc["id"] = uuid.uuid4().hex
        doc["created_at"] = now
        doc["error_log"] = []
        doc["last_used_at"] = None
        await db[COLLECTION].insert_one(doc)


async def get_secret(
    tenant_id: str,
    provider_key: str,
    *,
    db=None,
    touch: bool = True,
) -> Optional[str]:
    """Return decrypted plaintext, or ``None`` if no record exists.

    Bumps ``last_used_at`` when ``touch=True`` (default) so the UI
    reflects real usage. Callers that just want to *check* whether a
    connection exists should use ``connection_summary`` instead —
    that path never touches the ciphertext.
    """
    if db is None:
        db = _default_db()
    row = await db[COLLECTION].find_one(
        {"tenant_id": tenant_id, "provider_key": provider_key}
    )
    if not row:
        return None
    rec = EncryptedRecord(
        encrypted_blob=row["encrypted_blob"],
        iv=row["iv"],
        auth_tag=row["auth_tag"],
        dek_wrapped=row.get("dek_wrapped"),
    )
    pt = decrypt(rec)
    if touch:
        try:
            await db[COLLECTION].update_one(
                {"id": row["id"]},
                {"$set": {"last_used_at": _now_iso()}},
            )
        except Exception:  # pragma: no cover — best-effort
            pass
    return pt


async def remove_secret(
    tenant_id: str,
    provider_key: str,
    *,
    db=None,
) -> bool:
    """Delete the row. Returns ``True`` if a row was removed."""
    if db is None:
        db = _default_db()
    res = await db[COLLECTION].delete_one(
        {"tenant_id": tenant_id, "provider_key": provider_key}
    )
    return res.deleted_count > 0


async def list_connections(
    tenant_id: str,
    *,
    db=None,
) -> List[ConnectionSummary]:
    """All safe-to-serve connection summaries for a tenant."""
    if db is None:
        db = _default_db()
    out: List[ConnectionSummary] = []
    async for row in db[COLLECTION].find({"tenant_id": tenant_id}):
        out.append(_summary_from_row(row))
    return out


async def connection_summary(
    tenant_id: str,
    provider_key: str,
    *,
    db=None,
) -> Optional[ConnectionSummary]:
    """Single summary — never touches ciphertext."""
    if db is None:
        db = _default_db()
    row = await db[COLLECTION].find_one(
        {"tenant_id": tenant_id, "provider_key": provider_key}
    )
    if not row:
        return None
    return _summary_from_row(row)


async def mark_used(
    tenant_id: str,
    provider_key: str,
    *,
    db=None,
) -> None:
    if db is None:
        db = _default_db()
    await db[COLLECTION].update_one(
        {"tenant_id": tenant_id, "provider_key": provider_key},
        {"$set": {"last_used_at": _now_iso()}},
    )


async def log_error(
    tenant_id: str,
    provider_key: str,
    *,
    code: str,
    message: str,
    db=None,
) -> None:
    """Append a compact error entry. NEVER include plaintext or
    request bodies in ``message``. Cap at 20 entries."""
    if db is None:
        db = _default_db()
    entry = {"at": _now_iso(), "code": code, "message": message[:400]}
    # Push then $slice to keep the tail bounded.
    await db[COLLECTION].update_one(
        {"tenant_id": tenant_id, "provider_key": provider_key},
        {
            "$push": {
                "error_log": {"$each": [entry], "$slice": -_ERROR_LOG_CAP}
            },
            "$set": {"connected_status": ConnectionStatus.ERROR.value},
        },
    )
