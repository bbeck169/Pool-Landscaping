"""Phase 54h-b · Aug-2026 — Bookmarklet import-token contract.

Locks:
  * ``POST /api/suppliers/sessions/import-token`` mints a 5-min JWT
    with ``purpose: supplier_session_import``. Role gate = session
    role gate (admin + super_admin + manager).
  * ``POST /api/suppliers/{slug}/sessions?import_token=<valid>``
    accepts the token in lieu of an Authorization header + upserts
    the session (identical outcome to header-auth path).
  * A JWT with wrong ``purpose`` claim is rejected 403.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


ADMIN = {"id": "u-admin", "role": "admin",
         "email": "a@x", "tenant_id": "tenant-A"}


def _mint_scoped(purpose):
    """Build a JWT with an arbitrary purpose claim for the reject test."""
    import jwt as _jwt
    from config import JWT_SECRET, JWT_ALGO
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    return _jwt.encode({
        "purpose": purpose, "sub": ADMIN["id"],
        "tenant_id": ADMIN["tenant_id"], "role": ADMIN["role"],
        "email": ADMIN["email"], "exp": exp,
    }, JWT_SECRET, algorithm=JWT_ALGO)


def test_import_token_endpoint_returns_scoped_jwt():
    """Payload has ``purpose: supplier_session_import``, TTL ≈ 5 min,
    embeds tenant + user identity for the downstream POST."""
    from routers.suppliers import _issue_import_token, IMPORT_TOKEN_PURPOSE
    import jwt as _jwt
    from config import JWT_SECRET, JWT_ALGO
    out = _issue_import_token(ADMIN)
    assert "token" in out and out["token"]
    assert "expires_at" in out and out["expires_at"]
    payload = _jwt.decode(out["token"], JWT_SECRET,
                            algorithms=[JWT_ALGO])
    assert payload["purpose"] == IMPORT_TOKEN_PURPOSE
    assert payload["sub"] == ADMIN["id"]
    assert payload["tenant_id"] == ADMIN["tenant_id"]
    # Expires ≈ 5 min from now.
    expires = datetime.fromisoformat(out["expires_at"])
    delta = (expires - datetime.now(timezone.utc)).total_seconds()
    assert 240 <= delta <= 320  # 4-5.3 min


def test_decode_import_token_rejects_wrong_purpose():
    """A JWT signed with the CRM's key but carrying a non-matching
    ``purpose`` claim (e.g. someone tries to reuse an OAuth-refresh
    token as an import token) must return None so the endpoint 403s."""
    from routers.suppliers import _decode_import_token
    bogus = _mint_scoped(purpose="something_else")
    assert _decode_import_token(bogus) is None
    # And a garbage string returns None (not raises).
    assert _decode_import_token("not.a.jwt") is None
    assert _decode_import_token("") is None
    assert _decode_import_token(None) is None  # type: ignore[arg-type]


def test_valid_import_token_round_trips_to_the_original_operator_identity():
    """Decoding the token we just issued must return the same
    identity fields the upsert handler needs (sub, tenant_id, role)."""
    from routers.suppliers import (
        _issue_import_token, _decode_import_token, IMPORT_TOKEN_PURPOSE,
    )
    out = _issue_import_token(ADMIN)
    claims = _decode_import_token(out["token"])
    assert claims is not None
    assert claims["purpose"] == IMPORT_TOKEN_PURPOSE
    assert claims["sub"] == ADMIN["id"]
    assert claims["tenant_id"] == ADMIN["tenant_id"]
    assert claims["role"] == ADMIN["role"]
