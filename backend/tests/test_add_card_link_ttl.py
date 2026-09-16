"""Feb-2026 · Add-card magic-link TTL regression guard.

Locks in the 7-day default TTL for the ``add_card`` magic-link
purpose. Independent from other magic-link purposes (login,
invoice-pay, quote-approve) which have their own TTLs and are not
touched.
"""
from __future__ import annotations

import os
import time

import jwt

from services.add_card_links import (
    encode_add_card_token, decode_add_card_token,
    ADD_CARD_LINK_TTL_SECONDS, JWT_SECRET, JWT_ALGO,
)


_TOL_SECONDS = 5


def test_add_card_ttl_constant_is_7_days():
    """The single source of truth for the add-card link duration is
    the module-level ``ADD_CARD_LINK_TTL_SECONDS`` constant, which
    resolves to 604800 (7 days) unless
    ``PORTAL_ADD_CARD_LINK_TTL_HOURS`` overrides it."""
    override = os.environ.get("PORTAL_ADD_CARD_LINK_TTL_HOURS")
    expected_hours = int(override) if (override or "").isdigit() else 24 * 7
    assert ADD_CARD_LINK_TTL_SECONDS == expected_hours * 3600


def test_encoded_token_exp_minus_iat_equals_7d():
    """Concrete claim-level assertion — mint a token and confirm
    ``exp - iat`` is 604800 ± tolerance. This is the invariant the
    portal add-card page relies on to keep links usable across a
    typical customer's inbox check cadence."""
    tok = encode_add_card_token("cust_ttl_test", "tnt_ttl_test")
    payload = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
    assert "iat" in payload, f"token missing iat claim: {payload}"
    assert "exp" in payload
    delta = int(payload["exp"]) - int(payload["iat"])
    assert abs(delta - 604800) <= _TOL_SECONDS, (
        f"expected 7d TTL (604800s), got {delta}s"
    )


def test_freshly_minted_token_verifies_immediately():
    """A token minted just now must decode cleanly — no clock skew /
    ``iat in the future`` false-positives."""
    tok = encode_add_card_token("cust_now", "tnt_now")
    payload = decode_add_card_token(tok)
    assert payload["customer_id"] == "cust_now"
    assert payload["tenant_id"]  == "tnt_now"
    assert payload["sub"]        == "add_card"


def test_token_still_valid_before_expiry():
    """Simulate ``now`` well inside the token's validity window by
    minting a token whose ``exp - iat = 7d`` and confirming decode
    succeeds at any point before that window closes. Since the
    natural TTL is 7d, a fresh token trivially satisfies the case —
    we assert the decode path with a token whose expiry is close to
    but inside the window (via an explicit ``ttl_seconds`` override
    that puts exp 30s in the future)."""
    tok = encode_add_card_token(
        "cust_soon", "tnt_soon", ttl_seconds=30,
    )
    payload = decode_add_card_token(tok)
    assert payload["customer_id"] == "cust_soon"


def test_token_rejected_after_expiry():
    """Mint a token that already expired (``ttl_seconds=1``, then
    wait a beat) and confirm the decoder raises 401 ``Link expired``.
    Guards against a future refactor that accidentally sets a
    non-expiring token."""
    from fastapi import HTTPException
    tok = encode_add_card_token(
        "cust_stale", "tnt_stale", ttl_seconds=1,
    )
    time.sleep(1.5)
    try:
        decode_add_card_token(tok)
    except HTTPException as e:
        assert e.status_code == 401
        assert "expired" in str(e.detail).lower()
    else:
        raise AssertionError("expected HTTPException, got none")


def test_other_magic_link_purposes_are_unaffected():
    """Defense-in-depth — the TTL constant lives inside
    ``services.add_card_links`` and is namespaced to that purpose.
    Confirm the module exports the ``ADD_CARD_LINK_TTL_SECONDS``
    constant (with the explicit ``ADD_CARD_LINK`` prefix) rather
    than an ambient ``TTL_SECONDS`` that could accidentally get
    re-used by unrelated link types. Login / invoice-pay /
    quote-approve each have their own TTL inside their own
    module — see ``routers/auth.py``, ``routers/invoice_magic_view.py``,
    ``routers/quotes.py``."""
    import services.add_card_links as mod
    public = [n for n in dir(mod) if "TTL" in n and not n.startswith("_")]
    assert public == ["ADD_CARD_LINK_TTL_SECONDS"], public
    # No generic / bare ``TTL_SECONDS`` sneaking in that could get
    # imported by another link-purpose module by mistake.
    assert not hasattr(mod, "TTL_SECONDS")
