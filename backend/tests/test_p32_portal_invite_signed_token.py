"""Phase P32 · Feb-2026 — Portal magic-link signed-token audit lint.

Locks in the existing four-helper claim architecture in
:mod:`services.portal_magic_links` so a future refactor cannot
accidentally introduce a wide-scope token that could be replayed
across surfaces. Complements the audit report — no functional
change to the module was needed because every existing mint helper
is already:

* Signed with HS256 via ``jwt.encode(..., JWT_SECRET, ...)``.
* Carries ``tenant_id`` + ``customer_id`` (plus a resource id per
  scope: ``job_id`` / ``invoice_id`` / ``estimate_id`` — omitted
  on the ``portal_home`` variant).
* Carries an explicit ``iat`` + ``exp`` claim (never a bare
  ``ttl_seconds`` field — expiry is enforced by the JWT lib on
  ``decode`` via the ``exp`` claim, not by us).
* Uses a DISTINCT ``sub`` (purpose) claim so a leaked
  ``portal_invoice_pay`` token can NEVER be replayed as a
  ``portal_estimate_view`` token or the reverse (verify site
  rejects with 401 ``token_wrong_scope``).

Coverage
--------
1. Every ``mint_*_token`` helper stamps a ``sub`` claim.
2. Every ``verify_*_token`` helper rejects the wrong ``sub``
   with HTTP 401 ``token_wrong_scope`` (cross-scope replay guard).
3. Every mint helper embeds ``tenant_id`` + ``customer_id`` in
   the resulting JWT payload.
4. Every mint helper stamps ``iat`` + ``exp`` claims.
5. TTL contract — spot-check each helper's default TTL matches
   the module's stated context contract. Ops or a future maintainer
   who wants to change a TTL must update both the module docstring
   AND this test (forces the change to be intentional).
6. P32 recommendation surface — a NEW 14-day
   ``purpose: "portal_invite"`` helper does NOT exist yet. This
   test documents that gap so future work (see P32.1 build spec)
   is anchored to a positive assertion rather than a comment.

Regression
----------
Runs alongside ``test_p30_*.py`` (the Stripe Setup Session
signed-token flow) — the two claim architectures MUST stay
separate. A Stripe ``setup_intent`` metadata payload can NEVER
be replayed as a portal magic-link token and vice versa.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from fastapi import HTTPException

from config import JWT_ALGO, JWT_SECRET


_PORTAL_ML_MODULE = (
    Path(__file__).resolve().parents[1]
    / "services" / "portal_magic_links.py"
)


# ═════════════════════════════════════════════════════════════════════
# Helper claim + purpose matrix (source of truth for the assertions
# below). Keyed by mint helper name.
# ═════════════════════════════════════════════════════════════════════
_HELPER_MATRIX = {
    "mint_job_view_token": {
        "verify": "verify_job_view_token",
        "sub": "job_view",
        "extra_id_arg": "job_id",
        "extra_id_claim": "job_id",
        # P34 · Feb-2026 — unified TTL 168h across all four helpers.
        "ttl_hours_default": 168,
    },
    "mint_invoice_pay_token": {
        "verify": "verify_invoice_pay_token",
        "sub": "portal_invoice_pay",
        "extra_id_arg": "invoice_id",
        "extra_id_claim": "invoice_id",
        "ttl_hours_default": 168,
    },
    "mint_estimate_view_token": {
        "verify": "verify_estimate_view_token",
        "sub": "portal_estimate_view",
        "extra_id_arg": "estimate_id",
        "extra_id_claim": "estimate_id",
        "ttl_hours_default": 168,
    },
    "mint_portal_home_token": {
        "verify": "verify_portal_home_token",
        "sub": "portal_home",
        "extra_id_arg": None,
        "extra_id_claim": None,
        "ttl_hours_default": 168,
    },
}


def _mint(name: str, *, ttl_hours=None):
    """Invoke ``services.portal_magic_links.<name>`` with a canonical
    (customer, tenant, [+resource]) triple. Optional ``ttl_hours``
    override for expiry-boundary tests."""
    import services.portal_magic_links as pml
    meta = _HELPER_MATRIX[name]
    kwargs = {"customer_id": "c-p32", "tenant_id": "t-p32"}
    if meta["extra_id_arg"]:
        kwargs[meta["extra_id_arg"]] = f"r-p32-{meta['extra_id_arg']}"
    if ttl_hours is not None:
        kwargs["ttl_hours"] = ttl_hours
    return getattr(pml, name)(**kwargs)


# ═════════════════════════════════════════════════════════════════════
# 1. Every mint helper stamps a ``sub`` claim, matching the matrix.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("helper", list(_HELPER_MATRIX.keys()))
def test_p32_every_mint_helper_stamps_sub_claim(helper):
    tok = _mint(helper)
    payload = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
    expected_sub = _HELPER_MATRIX[helper]["sub"]
    assert payload["sub"] == expected_sub, (
        f"{helper} stamped sub={payload.get('sub')!r} "
        f"(expected {expected_sub!r})"
    )


# ═════════════════════════════════════════════════════════════════════
# 2. Cross-scope replay guard — every verifier rejects tokens
#    minted with a different helper's ``sub`` claim.
# ═════════════════════════════════════════════════════════════════════
def test_p32_cross_scope_replay_is_blocked_on_every_verifier():
    import services.portal_magic_links as pml
    helpers = list(_HELPER_MATRIX.keys())
    for mint_name in helpers:
        tok = _mint(mint_name)
        # This token has ``sub`` == the mint helper's declared value.
        # Every OTHER verifier MUST reject it with HTTP 401
        # token_wrong_scope.
        for verify_name in [
            _HELPER_MATRIX[h]["verify"] for h in helpers
            if h != mint_name
        ]:
            with pytest.raises(HTTPException) as ei:
                getattr(pml, verify_name)(tok)
            assert ei.value.status_code == 401, (
                f"{verify_name} did not 401 on a {mint_name} token"
            )
            # ``detail`` should be the stable scope-mismatch string.
            assert ei.value.detail == "token_wrong_scope", (
                f"{verify_name} produced detail={ei.value.detail!r} "
                f"(expected 'token_wrong_scope') on a {mint_name} "
                f"token — cross-scope replay guard is not firing"
            )


# ═════════════════════════════════════════════════════════════════════
# 3. Every mint helper embeds ``tenant_id`` + ``customer_id``.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("helper", list(_HELPER_MATRIX.keys()))
def test_p32_every_token_carries_tenant_and_customer_ids(helper):
    tok = _mint(helper)
    payload = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
    assert payload.get("tenant_id") == "t-p32"
    assert payload.get("customer_id") == "c-p32"
    extra = _HELPER_MATRIX[helper]["extra_id_claim"]
    if extra:
        assert payload.get(extra) == f"r-p32-{extra}"


# ═════════════════════════════════════════════════════════════════════
# 4. Every mint helper stamps ``iat`` + ``exp`` claims.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("helper", list(_HELPER_MATRIX.keys()))
def test_p32_every_token_has_iat_and_exp_claims(helper):
    tok = _mint(helper)
    payload = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
    assert "iat" in payload
    assert "exp" in payload
    # Values are Unix seconds (numeric). PyJWT normalizes datetime→int.
    assert isinstance(payload["iat"], int)
    assert isinstance(payload["exp"], int)
    assert payload["exp"] > payload["iat"]


# ═════════════════════════════════════════════════════════════════════
# 5. Default TTL contract — must match the matrix.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("helper", list(_HELPER_MATRIX.keys()))
def test_p32_default_ttl_matches_documented_context(helper):
    tok = _mint(helper)
    payload = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
    expected_hours = _HELPER_MATRIX[helper]["ttl_hours_default"]
    span_hours = (payload["exp"] - payload["iat"]) / 3600
    # ±2 seconds jitter for the datetime.now(timezone.utc) call site.
    assert abs(span_hours - expected_hours) < 0.01, (
        f"{helper} default TTL drifted: got {span_hours}h, "
        f"expected {expected_hours}h. If this is intentional, "
        f"update _HELPER_MATRIX AND the module docstring together."
    )


# ═════════════════════════════════════════════════════════════════════
# 6. Expiry-boundary guard on the portal_home helper — the closest
#    match to a "portal invite" surface. If the P32.1 build spec
#    later lands a new ``mint_portal_invite_token`` at 14d TTL,
#    THAT helper gets its own test; this one locks the 48h
#    ``portal_home`` contract in place.
# ═════════════════════════════════════════════════════════════════════
def test_p32_portal_home_token_rejects_expired_beyond_ttl():
    import services.portal_magic_links as pml
    # Mint a token with ttl_hours=1 → will be marked expired below
    # by re-encoding the payload with an ``exp`` in the past.
    tok = pml.mint_portal_home_token(
        customer_id="c-p32", tenant_id="t-p32", ttl_hours=1,
    )
    payload = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
    # Move ``exp`` 5 minutes into the past.
    payload["exp"] = int(
        (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp(),
    )
    stale = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    with pytest.raises(HTTPException) as ei:
        pml.verify_portal_home_token(stale)
    assert ei.value.status_code == 401
    assert ei.value.detail == "token_invalid_or_expired"


# ═════════════════════════════════════════════════════════════════════
# 7. Wrong-secret token → 401 (signature verification).
# ═════════════════════════════════════════════════════════════════════
def test_p32_token_signed_with_wrong_secret_is_rejected():
    import services.portal_magic_links as pml
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "portal_home",
        "customer_id": "c-p32", "tenant_id": "t-p32",
        "iat": now,
        "exp": now + timedelta(hours=48),
    }
    forged = jwt.encode(payload, "not-the-real-secret", algorithm=JWT_ALGO)
    with pytest.raises(HTTPException) as ei:
        pml.verify_portal_home_token(forged)
    assert ei.value.status_code == 401
    assert ei.value.detail == "token_invalid_or_expired"


# ═════════════════════════════════════════════════════════════════════
# 8. P30 Stripe cross-purpose replay guard — a ``card_add_setup``
#    metadata token / any Stripe-flavored token cannot be replayed
#    as a portal magic-link. The two systems don't even share the
#    same signing story (Stripe signs with the webhook secret; our
#    magic-links sign with JWT_SECRET), but as a belt-and-braces
#    lint the P30 metadata SHAPE ({source: "card_add_setup", ...})
#    is not accepted by any portal verifier.
# ═════════════════════════════════════════════════════════════════════
def test_p32_p30_stripe_metadata_shape_is_not_a_portal_token():
    import services.portal_magic_links as pml
    # Mint a JWT-shaped payload with the P30 Stripe metadata KEYS.
    # If some future refactor accidentally unified the token space,
    # this would silently redeem — the ``sub`` guard rejects it.
    now = datetime.now(timezone.utc)
    p30_shaped = {
        "source": "card_add_setup",
        "crm_tenant_id": "t-p32", "crm_customer_id": "c-p32",
        "flow": "card_add_setup",
        "iat": now, "exp": now + timedelta(days=1),
    }
    token = jwt.encode(p30_shaped, JWT_SECRET, algorithm=JWT_ALGO)
    for verify_name in ("verify_job_view_token",
                          "verify_invoice_pay_token",
                          "verify_estimate_view_token",
                          "verify_portal_home_token"):
        with pytest.raises(HTTPException) as ei:
            getattr(pml, verify_name)(token)
        assert ei.value.status_code == 401
        # Wrong-scope OR malformed (both fail closed).
        assert ei.value.detail in (
            "token_wrong_scope", "token_malformed",
            "token_invalid_or_expired",
        )


# ═════════════════════════════════════════════════════════════════════
# 9. P32 recommendation surface — assert the NEW 14-day
#    ``portal_invite`` helper is NOT YET present. Flips to a
#    positive assertion when P32.1 lands; the presence-check is a
#    tripwire so nobody adds it under a subtly-wrong claim shape.
# ═════════════════════════════════════════════════════════════════════
def test_p32_no_portal_invite_helper_yet_awaiting_p32_1_build_spec():
    """As of the P32 audit, no ``mint_portal_invite_token`` /
    ``verify_portal_invite_token`` helper exists. When P32.1 adds
    them, THIS test is the tripwire that forces the maintainer to
    also add a test alongside — see the P32 audit wrap-up for
    the required claim shape:
    ``{sub: "portal_invite", tenant_id, customer_id, iat,
       exp: iat + 14*86400}``.
    """
    import services.portal_magic_links as pml
    assert not hasattr(pml, "mint_portal_invite_token"), (
        "P32.1 helper appeared — add a dedicated 14-day contract "
        "test alongside this tripwire (mint + verify + cross-scope "
        "replay guard) before flipping this assertion positive."
    )
    assert not hasattr(pml, "verify_portal_invite_token"), (
        "P32.1 verify helper appeared — see above."
    )


# ═════════════════════════════════════════════════════════════════════
# 10. Source-lint — the module contains NO plain-UUID / opaque-token
#     invite paths. Every mint helper uses ``jwt.encode(...)``, never
#     ``secrets.token_urlsafe`` (that pattern lives in the password-
#     reset flow, which is intentional per the audit).
# ═════════════════════════════════════════════════════════════════════
def test_p32_portal_magic_links_module_uses_only_jwt_encode():
    src = _PORTAL_ML_MODULE.read_text(encoding="utf-8")
    assert "jwt.encode(" in src
    # secrets.token_urlsafe belongs to the password-reset flow
    # (portal_admin.py:396), NOT the magic-link module.
    assert "secrets.token_urlsafe" not in src, (
        "portal_magic_links.py grew a secrets.token_urlsafe caller "
        "— that's the password-reset opaque-token pattern, not the "
        "signed-token magic-link pattern. Fix the drift."
    )
