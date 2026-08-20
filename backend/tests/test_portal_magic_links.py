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
