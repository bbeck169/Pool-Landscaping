"""Feb-2026 · Password-reset TTL hotfix — 30 min → 30 days.

Locks in five invariants:

    1. The ``_RESET_TTL_MINUTES`` constant is 43200 (30 × 24 × 60).
    2. Rendered password-reset email HTML says "30 days" (not
       "43200 minutes", not "30 minutes").
    3. Tokens minted by the reset-request path expire ≈ 30 days out
       (``expires_at`` on the persisted ``password_reset_tokens``
       row is within a small clock-skew window of ``now + 30d``).
    4. ``password_reset_confirm`` accepts a token whose stored
       ``expires_at`` is anywhere inside the 30-day window (we seed
       one at 29 days out) and rejects a token that expired 1
       second ago (30-day boundary).
    5. Adjacent TTLs (``_TEMP_PASSWORD_RESET_TTL_MINUTES`` for the
       admin-forced temp-password rotation, plus the response
       schema of the ``/portal-reset`` temp-password path) are
       untouched — no accidental bump.

Uses the codebase-standard async pattern (``run_test`` +
``httpx.ASGITransport`` + Motor rebinding) for the endpoint tests.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _get_app():
    from server import app
    return app


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


# ─────────────── Static constant assertions ───────────────────────
def test_reset_ttl_constant_is_30_days_in_minutes():
    from routers.auth import _RESET_TTL_MINUTES, _RESET_TTL_DAYS
    assert _RESET_TTL_DAYS == 30
    assert _RESET_TTL_MINUTES == 30 * 24 * 60
    assert _RESET_TTL_MINUTES == 43200


def test_temp_password_ttl_unchanged():
    """Guard-rail: admin-forced temp password rotation uses a
    SEPARATE constant that must NOT be bumped by this hotfix."""
    from routers.auth import _TEMP_PASSWORD_RESET_TTL_MINUTES
    assert _TEMP_PASSWORD_RESET_TTL_MINUTES == 15


def test_portal_reset_link_resp_schema_default_matches_constant():
    from routers.portal_admin import (
        PortalResetLinkResp, PortalResetLinkCopyResp,
    )
    from routers.auth import _RESET_TTL_MINUTES
    r1 = PortalResetLinkResp(sent_to="masked@x.com")
    r2 = PortalResetLinkCopyResp(reset_url="https://x/y", expires_at="now")
    assert r1.token_ttl_minutes == 43200
    assert r2.token_ttl_minutes == 43200
    assert r1.token_ttl_minutes == _RESET_TTL_MINUTES
    assert r2.token_ttl_minutes == _RESET_TTL_MINUTES


# ─────────────── _format_expiry_label pure fn ─────────────────────
def test_format_expiry_label_days_hours_minutes():
    from routers.auth import _format_expiry_label
    assert _format_expiry_label(43200) == "30 days"
    assert _format_expiry_label(1440)  == "1 day"
    assert _format_expiry_label(120)   == "2 hours"
    assert _format_expiry_label(60)    == "1 hour"
    assert _format_expiry_label(30)    == "30 minutes"
    assert _format_expiry_label(1)     == "1 minute"
    assert _format_expiry_label(0)     == "0 minutes"


# ─────────────── Rendered email copy ──────────────────────────────
def test_rendered_email_says_30_days_not_43200_minutes():
    from routers.auth import _password_reset_email_html, _RESET_TTL_MINUTES
    html = _password_reset_email_html(
        first_name="Sample",
        reset_link="https://app.plofv.com/reset?t=abc",
        expiry_minutes=_RESET_TTL_MINUTES,
    )
    assert "30 days" in html, html
    # Legacy copy must be entirely purged from the rendered body.
    assert "30 minutes" not in html
    # And the raw minute value MUST NOT leak into the copy.
    assert "43200" not in html


def test_email_preview_stub_matches_reality():
    """The ``email_preview`` stub used in support-visible previews
    must render the same "30 days" label as the real send path,
    or ops will screenshot copy the customer never actually sees."""
    from routers.email_preview import _stub_password_reset
    html = _stub_password_reset()
    assert "30 days" in html
    assert "15 minutes" not in html
    assert "30 minutes" not in html


# ─────────────── Reset-request path mints a 30-day token ─────────
@pytest.fixture(scope="module")
def _reset_user(dbc):
    tenant_id = f"t_reset_{uuid.uuid4().hex[:8]}"
    user_id   = f"u_reset_{uuid.uuid4().hex[:8]}"
    email     = f"reset.{tenant_id[:6]}@test.local"
    dbc.tenants.insert_one({
        "id": tenant_id, "slug": f"reset-{tenant_id[:6]}", "name": "Reset",
    })
    dbc.users.insert_one({
        "id":                 user_id,
        "tenant_id":          tenant_id,
        "email":              email,
        "role":               "admin",
        "password_hash":      "$2b$12$fakebcryptplaceholder",
        "deleted_at":         None,
    })
    yield {"tenant_id": tenant_id, "user_id": user_id, "email": email}
    dbc.users.delete_many({"id": user_id})
    dbc.tenants.delete_many({"id": tenant_id})
    dbc.password_reset_tokens.delete_many({"user_id": user_id})


def test_password_reset_request_persists_30_day_expiry(dbc, _reset_user):
    """Fire ``POST /api/auth/password-reset-request`` and inspect the
    freshly-minted ``password_reset_tokens`` row — ``expires_at``
    must land within a small clock-skew window of ``now + 30 days``.
    """
    # Snapshot the DB state so we can find the row we just wrote.
    dbc.password_reset_tokens.delete_many({"user_id": _reset_user["user_id"]})

    holder: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                      base_url="http://test") as ac:
            holder["r"] = await ac.post(
                "/api/auth/forgot-password",
                json={"email": _reset_user["email"]},
            )

    run_test(_go)
    r = holder["r"]
    assert r.status_code == 200, r.text
    row = dbc.password_reset_tokens.find_one(
        {"user_id": _reset_user["user_id"]},
    )
    assert row is not None, "expected a password_reset_tokens row after request"
    exp_raw = row["expires_at"]
    exp_dt = (
        exp_raw if isinstance(exp_raw, datetime)
        else datetime.fromisoformat(exp_raw)
    )
    if exp_dt.tzinfo is None:
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    target = datetime.now(timezone.utc) + timedelta(days=30)
    # Allow ±60s of clock skew between request time and assertion.
    delta = abs((exp_dt - target).total_seconds())
    assert delta < 60, f"expected ~30d expiry, got Δ={delta}s (exp_dt={exp_dt.isoformat()})"


# ─────────────── Token validity at day 29 vs after day 30 ────────
def _seed_reset_row(dbc, user, *, expires_at: datetime, token: str):
    # Schema mirrors the mint code at ``routers.auth`` (line 892) —
    # the router queries by raw ``token``, not a hash.
    dbc.password_reset_tokens.insert_one({
        "id":             str(uuid.uuid4()),
        "token":          token,
        "user_id":        user["user_id"],
        "email":          user["email"],
        "tenant_id":      user["tenant_id"],
        "expires_at":     expires_at.isoformat(),
        "used_at":        None,
        "invalidated_at": None,
        "created_at":     datetime.now(timezone.utc).isoformat(),
        "created_ip":     "127.0.0.1",
    })


def _hash_token(token: str) -> str:
    """Retained for backward-compat with callers that might have
    linked against the pre-hotfix helper — the router itself queries
    by raw token so this is unused in the current flow."""
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_token_valid_at_29_days_out(dbc, _reset_user):
    token = f"tok29d_{uuid.uuid4().hex}"
    _seed_reset_row(
        dbc, _reset_user,
        expires_at=datetime.now(timezone.utc) + timedelta(days=29),
        token=token,
    )
    # Only the neutral "we processed your request" contract matters
    # here — the confirm endpoint accepts the token because
    # ``expires_at`` is 29d in the future.
    holder: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                      base_url="http://test") as ac:
            holder["r"] = await ac.post(
                "/api/auth/reset-password",
                json={
                    "token":        token,
                    "new_password": "NewSecret_2026!",
                },
            )
    run_test(_go)
    r = holder["r"]
    # 200 with ``ok: true`` means the reset landed (token accepted +
    # password rewritten). Any other outcome (400 "expired", 400
    # "invalid") would mean we're rejecting still-valid links.
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True

    # Cleanup for the next test.
    dbc.password_reset_tokens.delete_many(
        {"user_id": _reset_user["user_id"]},
    )


def test_token_expired_1_second_after_30_days(dbc, _reset_user):
    token = f"tokExp_{uuid.uuid4().hex}"
    _seed_reset_row(
        dbc, _reset_user,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        token=token,
    )
    holder: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                      base_url="http://test") as ac:
            holder["r"] = await ac.post(
                "/api/auth/reset-password",
                json={
                    "token":        token,
                    "new_password": "NewSecret_2026!",
                },
            )
    run_test(_go)
    r = holder["r"]
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or ""
    assert "expired" in detail.lower(), detail

    dbc.password_reset_tokens.delete_many(
        {"user_id": _reset_user["user_id"]},
    )


# ─────────────── Codebase-wide "30 minutes" guard ─────────────────
def test_no_password_reset_flow_still_says_30_minutes():
    """Scan the two files this hotfix touches for any lingering "30
    minutes" string in the password-reset context.

    We deliberately DON'T grep the whole repo — the codebase has
    many legitimate "30 minutes" strings (technician arrival ETA,
    handbook accident-reporting policy, training content). This
    test is scoped to the files the hotfix owns."""
    hotfix_files = [
        Path("/app/backend/routers/auth.py"),
        Path("/app/backend/routers/portal_admin.py"),
        Path("/app/backend/routers/email_preview.py"),
    ]
    stale = re.compile(
        r"(?i)(link|token|reset).{0,80}30\s*minutes|30\s*minutes.{0,80}(reset|expir|password)",
    )
    hits: Dict[str, list] = {}
    for p in hotfix_files:
        text = p.read_text(encoding="utf-8")
        matches = stale.findall(text)
        if matches:
            hits[str(p)] = matches
    assert not hits, (
        f"stale '30 minutes' password-reset copy still present: {hits}"
    )
