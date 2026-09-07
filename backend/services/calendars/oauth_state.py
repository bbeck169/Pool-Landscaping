"""Phase I1.7.c.3 · Feb-2026 — Signed, single-use OAuth state tokens.

Every ``/oauth/start`` call mints a state token that is::

    * HMAC-SHA256 signed with SECRETS_MASTER_KEY (existing env),
    * bound to (tenant_id, technician_user_id, provider_short, nonce),
    * time-boxed (exp <= 10min from mint),
    * single-use — the callback records the nonce in
      ``calendar_oauth_state_consumed`` and any replay raises
      ``OAuthStateReplayed``.

Rejection reasons on the callback path::

    * expired               -> OAuthStateExpired      (HTTP 400)
    * bad signature         -> OAuthStateTampered     (HTTP 400)
    * replay / consumed     -> OAuthStateReplayed     (HTTP 400)
    * malformed / missing   -> OAuthStateTampered     (HTTP 400)

Never trust the callback ``state`` param without ``verify_state_token``.
"""
from __future__ import annotations

import base64
import hmac
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


CONSUMED_COLLECTION = "calendar_oauth_state_consumed"

# Tokens must expire within 10 minutes of mint (user-locked P0 rule).
_MAX_TTL_SECONDS = 600


class OAuthStateError(Exception):
    """Base class for state-token errors."""


class OAuthStateExpired(OAuthStateError):
    pass


class OAuthStateReplayed(OAuthStateError):
    pass


class OAuthStateTampered(OAuthStateError):
    pass


def _hmac_key() -> bytes:
    """Reuse ``SECRETS_MASTER_KEY`` as the HMAC key. Fall back to a
    deterministic placeholder ONLY in test-mode; production boot
    validates the env var elsewhere (see services.secrets)."""
    key = (os.environ.get("SECRETS_MASTER_KEY") or "").encode()
    if not key:
        # Test/preview safety net — never happens in prod because
        # services.secrets refuses to boot without a master key.
        key = b"calendars-oauth-test-key-do-not-use-in-prod"
    return key


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(txt: str) -> bytes:
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)


def build_state_token(
    *, tenant_id: str, technician_user_id: str,
    provider_short: str, ttl_seconds: int = 300,
) -> str:
    """Mint a signed state token.  TTL is clamped to ``_MAX_TTL_SECONDS``
    so a mis-configured caller can never issue a long-lived state."""
    if ttl_seconds <= 0:
        ttl_seconds = 60
    if ttl_seconds > _MAX_TTL_SECONDS:
        ttl_seconds = _MAX_TTL_SECONDS
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=ttl_seconds)
    payload: Dict[str, Any] = {
        "t":  tenant_id,
        "u":  technician_user_id,
        "p":  provider_short,          # "google_calendar" | "outlook"
        "n":  uuid.uuid4().hex,        # nonce
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(_hmac_key(), body, hashlib.sha256).digest()
    return f"{_b64url_encode(body)}.{_b64url_encode(sig)}"


def _parse_payload(state: str) -> Dict[str, Any]:
    if not state or "." not in state:
        raise OAuthStateTampered("malformed state token (no dot)")
    body_b64, sig_b64 = state.rsplit(".", 1)
    try:
        body = _b64url_decode(body_b64)
        sig = _b64url_decode(sig_b64)
    except Exception as e:
        raise OAuthStateTampered(f"base64 decode failed: {e}") from e
    expected = hmac.new(_hmac_key(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise OAuthStateTampered("signature mismatch")
    try:
        return json.loads(body)
    except Exception as e:
        raise OAuthStateTampered(f"json decode failed: {e}") from e


async def verify_state_token(
    state: str, *,
    expect_provider_short: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """Validate signature + expiry + replay-protection. Returns the
    decoded payload dict ``{t, u, p, n, iat, exp}`` on success.
    On any failure raises the appropriate ``OAuthStateError`` subclass.
    """
    payload = _parse_payload(state)
    for req in ("t", "u", "p", "n", "exp"):
        if req not in payload:
            raise OAuthStateTampered(f"missing field: {req}")
    now = int(datetime.now(timezone.utc).timestamp())
    if int(payload["exp"]) < now:
        raise OAuthStateExpired(f"expired at {payload['exp']} < now {now}")
    if expect_provider_short and payload["p"] != expect_provider_short:
        raise OAuthStateTampered(
            f"provider mismatch: token={payload['p']} expected={expect_provider_short}"
        )
    # Replay protection: nonce is single-use per (tenant, tech, provider).
    if db is None:
        from config import db as _db  # local import — pytest env timing
        db = _db
    try:
        res = await db[CONSUMED_COLLECTION].insert_one({
            "nonce": payload["n"],
            "tenant_id": payload["t"],
            "technician_user_id": payload["u"],
            "provider": payload["p"],
            "consumed_at": datetime.now(timezone.utc).isoformat(),
            # Auto-drop after 24 h via TTL index (see boot idx creator).
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        })
        if not res.inserted_id:  # pragma: no cover — insert always returns id
            raise OAuthStateReplayed("insert returned no id")
    except Exception as e:
        # Duplicate-key error on the unique ``nonce`` index means replay.
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise OAuthStateReplayed(f"nonce already consumed: {payload['n']}") from e
        raise
    return payload


async def ensure_state_indexes(db) -> None:
    """Boot-time idempotent index creation. Called by
    ``services.calendars.dispatcher.ensure_indexes``."""
    await db[CONSUMED_COLLECTION].create_index("nonce", unique=True,
                                                 name="oauth_state_nonce_uniq")
    # TTL — drop consumed rows a day after callback so the collection
    # never grows unbounded. Mongo TTL fires on a background thread.
    await db[CONSUMED_COLLECTION].create_index(
        "expires_at", expireAfterSeconds=0, name="oauth_state_ttl",
    )
