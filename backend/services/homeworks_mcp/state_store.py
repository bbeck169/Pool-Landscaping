"""Feb-2026 · Homeworks OAuth state store (Mongo, 5-min TTL).

The ``state`` nonce is the OAuth CSRF token — bound one-shot to the
``code_verifier`` we send in the authorize URL. On the callback we look
up the state doc, extract the verifier, exchange the code, and delete
the doc. TTL cleanup handles abandoned flows automatically.

Collection shape (see ``ensure_indexes``)::

    {
      state_nonce:   str,        # 43 chars URL-safe (32 bytes entropy)
      code_verifier: str,        # 64-char PKCE verifier
      tenant_id:     str,
      user_id:       str,
      redirect_uri:  str,        # exact URI submitted in the /authorize call
      created_at:    datetime,   # server clock
      expires_at:    datetime,   # created_at + 5 min — TTL-indexed
    }

Rate-limit note: the ``/oauth/start`` route rate-limits per-user before
we ever write here. See :mod:`routers.integrations_homeworks_oauth`.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from config import db

logger = logging.getLogger("homeworks_mcp.state_store")

# 5 min per spec. TTL index is scoped to `expires_at`.
STATE_TTL_SECONDS = 5 * 60

# 32 bytes → 43 URL-safe chars via token_urlsafe. Comfortably above the
# 256-bit floor the OAuth 2.1 draft recommends.
_STATE_NONCE_BYTES = 32


_indexes_ensured = False


async def ensure_indexes() -> None:
    """Create the ``expires_at`` TTL index + unique ``state_nonce`` index.

    Idempotent — Mongo silently no-ops if the index already exists.
    """
    global _indexes_ensured
    if _indexes_ensured:
        return
    try:
        await db.homeworks_oauth_state.create_index(
            "state_nonce", unique=True
        )
        await db.homeworks_oauth_state.create_index(
            "expires_at", expireAfterSeconds=0
        )
        _indexes_ensured = True
    except Exception as exc:  # noqa: BLE001
        # Non-fatal: state docs still work without the TTL index, they
        # just don't get GC'd. Log and move on.
        logger.warning(
            "[homeworks_oauth] ensure_indexes noop: %s", exc,
        )


def generate_state_nonce() -> str:
    """Return 43 URL-safe chars (32 bytes of entropy)."""
    return secrets.token_urlsafe(_STATE_NONCE_BYTES)


async def create(
    *,
    state_nonce: str,
    code_verifier: str,
    tenant_id: str,
    user_id: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    doc = {
        "state_nonce": state_nonce,
        "code_verifier": code_verifier,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "redirect_uri": redirect_uri,
        "created_at": now,
        "expires_at": now + timedelta(seconds=STATE_TTL_SECONDS),
    }
    await ensure_indexes()
    await db.homeworks_oauth_state.insert_one(doc)
    return doc


async def pop(state_nonce: str) -> Optional[Dict[str, Any]]:
    """Fetch **and delete** the state doc atomically.

    Returns ``None`` if there is no matching doc, if the doc has
    expired, or if the underlying find/delete race lost. Callers MUST
    treat ``None`` as an auth failure.
    """
    if not state_nonce or not isinstance(state_nonce, str):
        return None
    doc = await db.homeworks_oauth_state.find_one_and_delete(
        {"state_nonce": state_nonce}
    )
    if not doc:
        return None
    # Belt-and-suspenders — TTL index sweeps every ~60s so an expired
    # doc could still be present at read time. Reject those explicitly.
    exp = doc.get("expires_at")
    if isinstance(exp, datetime):
        # Normalise naïve→aware so the compare doesn't blow up if some
        # Mongo driver strips the tzinfo.
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            return None
    doc.pop("_id", None)
    return doc
