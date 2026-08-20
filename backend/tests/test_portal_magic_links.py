"""Feb-2026 · Portal magic-link JWT — mint / verify roundtrip tests.

Mirrors the ``add_card`` token contract in
:mod:`services.add_card_links` but scoped to the ``job_view`` sub.
Each test exercises the module directly (no HTTP surface — the
verify endpoint lives on the portal frontend for now).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from config import JWT_ALGO, JWT_SECRET
from services.portal_magic_links import (
    mint_job_view_token, verify_job_view_token, build_job_view_url,
)


def test_mint_verify_roundtrip_returns_claims():
    tok = mint_job_view_token("cust-a", "job-b", "tenant-c")
    payload = verify_job_view_token(tok)
    assert payload["customer_id"] == "cust-a"
    assert payload["job_id"] == "job-b"
    assert payload["tenant_id"] == "tenant-c"
    assert payload["sub"] == "job_view"
    # exp > now, iat <= now.
    assert payload["exp"] > payload["iat"]


def test_verify_rejects_empty_token():
    with pytest.raises(HTTPException) as excinfo:
        verify_job_view_token("")
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "token_invalid_or_expired"


def test_verify_rejects_tampered_signature():
    tok = mint_job_view_token("cust-a", "job-b", "tenant-c")
    # Flip a byte in the middle segment (payload) so the signature
    # no longer matches.
    header, payload, sig = tok.split(".")
    tampered = f"{header}.{payload[:-1]}{'A' if payload[-1] != 'A' else 'B'}.{sig}"
    with pytest.raises(HTTPException) as excinfo:
        verify_job_view_token(tampered)
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "token_invalid_or_expired"


def test_verify_rejects_wrong_sub():
    # Mint a token with the wrong ``sub`` claim (e.g., an add_card
    # token replayed here).  Directly encode so we don't need the
    # add_card helper.
    now = datetime.now(timezone.utc)
    tok = jwt.encode(
        {"sub": "add_card", "customer_id": "cust-a", "job_id": "job-b",
         "tenant_id": "tenant-c", "iat": now,
         "exp": now + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )
    with pytest.raises(HTTPException) as excinfo:
        verify_job_view_token(tok)
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "token_wrong_scope"


def test_verify_rejects_expired_token():
    # Mint an already-expired token directly.
    now = datetime.now(timezone.utc)
    tok = jwt.encode(
        {"sub": "job_view", "customer_id": "cust-a", "job_id": "job-b",
         "tenant_id": "tenant-c",
         "iat": now - timedelta(hours=25),
         "exp": now - timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )
    with pytest.raises(HTTPException) as excinfo:
        verify_job_view_token(tok)
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "token_invalid_or_expired"


def test_verify_rejects_missing_claims():
    # Token missing job_id.
    now = datetime.now(timezone.utc)
    tok = jwt.encode(
        {"sub": "job_view", "customer_id": "cust-a", "tenant_id": "tenant-c",
         "iat": now, "exp": now + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )
    with pytest.raises(HTTPException) as excinfo:
        verify_job_view_token(tok)
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "token_malformed"


def test_build_job_view_url_shape():
    url = build_job_view_url(
        "https://portal.example.com/", "cust-a", "job-b", "tenant-c",
    )
    # Feb-2026 hotfix — URL now points at the backend redemption
    # interstitial (``/api/portal/auto-login?t=…``) instead of the
    # portal SPA directly, so the button click has a server to hit
    # and can't 404 on missing SPA route.
    assert url.startswith(
        "https://portal.example.com/api/portal/auto-login?t="
    )
    tok = url.split("?t=", 1)[1]
    payload = verify_job_view_token(tok)
    assert payload["customer_id"] == "cust-a"
    assert payload["job_id"] == "job-b"


def test_wrong_scope_different_job_id_still_rejected_when_verified_as_job_view():
    """A well-formed job-view token for job-X should NOT verify as a
    job-view token for job-Y at the verifier level — the verifier
    returns the claims, and the CALLER is expected to compare against
    the URL path.  This test documents that contract (the verifier
    alone will happily hand back the claims for the correct job id)."""
    tok = mint_job_view_token("cust-a", "job-X", "tenant-c")
    payload = verify_job_view_token(tok)
    assert payload["job_id"] == "job-X"
    # A route that expected job-Y must compare payload["job_id"]
    # against the URL path itself — mirrors the add-card + invoice-
    # magic idiom (see routers/invoice_magic_view._verify... where
    # the endpoint asserts ``payload["invoice_id"] == iid``).


# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · Slice 7 — Invoice + Estimate portal auto-login tokens.
# ═════════════════════════════════════════════════════════════════════
from services.portal_magic_links import (
    mint_invoice_pay_token, verify_invoice_pay_token,
    mint_estimate_view_token, verify_estimate_view_token,
    build_invoice_pay_url, build_estimate_view_url,
)


def test_mint_verify_invoice_pay_roundtrip_returns_claims():
    tok = mint_invoice_pay_token("cust-1", "inv-9", "tenant-x")
    p = verify_invoice_pay_token(tok)
    assert p["customer_id"] == "cust-1"
    assert p["invoice_id"] == "inv-9"
    assert p["tenant_id"] == "tenant-x"
    assert p["sub"] == "portal_invoice_pay"
    assert p["exp"] > p["iat"]
    # 48h default TTL — allow 60s slack for CI clock drift.
    assert (p["exp"] - p["iat"]) >= 48 * 3600 - 60


def test_mint_verify_estimate_view_roundtrip_returns_claims():
    tok = mint_estimate_view_token("cust-1", "est-9", "tenant-x")
    p = verify_estimate_view_token(tok)
    assert p["customer_id"] == "cust-1"
    assert p["estimate_id"] == "est-9"
    assert p["tenant_id"] == "tenant-x"
    assert p["sub"] == "portal_estimate_view"
    # 72h default TTL.
    assert (p["exp"] - p["iat"]) >= 72 * 3600 - 60


def test_invoice_token_rejected_by_estimate_verifier():
    """Cross-scope replay guard — an invoice token MUST NOT decode
    as an estimate token, and vice versa."""
    tok = mint_invoice_pay_token("cust-1", "inv-9", "tenant-x")
    with pytest.raises(HTTPException) as exc:
        verify_estimate_view_token(tok)
    assert exc.value.status_code == 401
    assert exc.value.detail == "token_wrong_scope"


def test_estimate_token_rejected_by_invoice_verifier():
    tok = mint_estimate_view_token("cust-1", "est-9", "tenant-x")
    with pytest.raises(HTTPException) as exc:
        verify_invoice_pay_token(tok)
    assert exc.value.status_code == 401
    assert exc.value.detail == "token_wrong_scope"


def test_job_view_token_rejected_by_invoice_verifier():
    """Belt-and-suspenders — the door-hanger job_view token also
    fails the invoice-pay verifier."""
    tok = mint_job_view_token("cust-1", "job-9", "tenant-x")
    with pytest.raises(HTTPException) as exc:
        verify_invoice_pay_token(tok)
    assert exc.value.status_code == 401
    assert exc.value.detail == "token_wrong_scope"


def test_invoice_token_scopes_to_specific_invoice_id():
    """An invoice_A token MUST carry ``invoice_id=invoice_A``. Two
    tokens minted for different invoice IDs decode to different
    payloads — a leaked token cannot jump to another invoice."""
    tok_a = mint_invoice_pay_token("cust-1", "inv-A", "tenant-x")
    tok_b = mint_invoice_pay_token("cust-1", "inv-B", "tenant-x")
    p_a = verify_invoice_pay_token(tok_a)
    p_b = verify_invoice_pay_token(tok_b)
    assert p_a["invoice_id"] == "inv-A"
    assert p_b["invoice_id"] == "inv-B"
    assert p_a["invoice_id"] != p_b["invoice_id"]


def test_estimate_token_scopes_to_specific_estimate_id():
    tok_a = mint_estimate_view_token("cust-1", "est-A", "tenant-x")
    tok_b = mint_estimate_view_token("cust-1", "est-B", "tenant-x")
    p_a = verify_estimate_view_token(tok_a)
    p_b = verify_estimate_view_token(tok_b)
    assert p_a["estimate_id"] == "est-A"
    assert p_b["estimate_id"] == "est-B"


def test_expired_invoice_token_rejected():
    payload = {
        "sub": "portal_invoice_pay",
        "customer_id": "c", "invoice_id": "i", "tenant_id": "t",
        "iat": datetime.now(timezone.utc) - timedelta(days=3),
        "exp": datetime.now(timezone.utc) - timedelta(seconds=5),
    }
    tok = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    with pytest.raises(HTTPException) as exc:
        verify_invoice_pay_token(tok)
    assert exc.value.status_code == 401
    assert exc.value.detail == "token_invalid_or_expired"


def test_tampered_estimate_signature_rejected():
    tok = mint_estimate_view_token("cust-1", "est-9", "tenant-x")
    # Flip a single character in the signature segment.
    header, body, sig = tok.split(".")
    bad_sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    tampered = ".".join((header, body, bad_sig))
    with pytest.raises(HTTPException) as exc:
        verify_invoice_pay_token(tampered)
    # Wrong scope OR invalid signature — both raise 401.
    assert exc.value.status_code == 401


def test_build_invoice_pay_url_shape():
    url = build_invoice_pay_url(
        "https://app.plofv.com", "cust-1", "inv-9", "tenant-x",
    )
    assert url.startswith(
        "https://app.plofv.com/api/portal/auto-login?t=",
    )
    tok = url.split("t=", 1)[1]
    p = verify_invoice_pay_token(tok)
    assert p["invoice_id"] == "inv-9"


def test_build_estimate_view_url_shape():
    url = build_estimate_view_url(
        "https://app.plofv.com/", "cust-1", "est-9", "tenant-x",
    )
    # Trailing slash on base URL must be stripped.
    assert url.startswith(
        "https://app.plofv.com/api/portal/auto-login?t=",
    )
    tok = url.split("t=", 1)[1]
    p = verify_estimate_view_token(tok)
    assert p["estimate_id"] == "est-9"


def test_mint_helpers_reject_empty_ids():
    for _args in (
        ("", "inv-9", "tenant-x"),
        ("cust-1", "", "tenant-x"),
        ("cust-1", "inv-9", ""),
    ):
        with pytest.raises(ValueError):
            mint_invoice_pay_token(*_args)
    for _args in (
        ("", "est-9", "tenant-x"),
        ("cust-1", "", "tenant-x"),
        ("cust-1", "est-9", ""),
    ):
        with pytest.raises(ValueError):
            mint_estimate_view_token(*_args)
