"""P2 #11 · Phase 1 · Feb-2026 — Backend tests for the Comms Email
Template test-send endpoint.

Covers the hardening matrix from the Phase 1 dispatch:

  1. Admin + no ``to`` → sends to admin's own email (safe default) →
     200 + ``db.sends`` row stamped ``kind="test_send"`` with the
     ``[TEST]`` subject prefix.
  2. Admin + ``to`` matching another tenant admin → 200.
  3. Admin + ``to`` matching an external arbitrary address → 400
     ``test_recipient_not_allowed``.
  4. Non-admin user (role=``technician``) → 403.
  5. Rate-limit — the 11th call inside a one-hour rolling window
     returns 429 with a ``Retry-After`` header.
  6. Audit-trail invariant — the ``db.sends`` row for the first case
     really DOES carry ``kind="test_send"`` AND a subject starting
     with ``"[TEST] "`` (so the normal send-history view can filter
     these out without losing the receipt).

The harness mirrors ``backend/tests/test_landscape_timeclock_dept_both.py``
— sync PyMongo for setup/assert, HTTP against the local pod, signed
JWTs so we don't drag the full auth stack into unit tests.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _tok(user_id: str, email: str, role: str,
          tenant_id: str) -> str:
    payload = {
        "sub": user_id, "email": email, "role": role,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


@pytest.fixture()
def tenant_id():
    tid = f"ctsnd-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"CTS {tid}", "slug": f"cts-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield tid
    # Tidy — nuke the fixture tenant + its users + any sends +
    # any email templates seeded by this run.
    _sync.sends.delete_many({"tenant_id": tid})
    _sync.email_templates.delete_many({"tenant_id": tid})
    for col in ("tenants", "users"):
        _sync[col].delete_many({"id": tid})
        _sync[col].delete_many({"tenant_id": tid})


def _seed_user(tenant_id: str, role: str, email: str | None = None) -> dict:
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = email or f"{uid}@cts.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"CTS {role}", "email": email,
    })
    return {"id": uid, "email": email, "role": role,
            "tenant_id": tenant_id,
            "token": _tok(uid, email, role, tenant_id)}


def _seed_template(tenant_id: str) -> str:
    code = f"tpl-{uuid.uuid4().hex[:8]}"
    _sync.email_templates.insert_one({
        "id": uuid.uuid4().hex, "tenant_id": tenant_id,
        "code": code, "name": "P2 #11 test tpl",
        "subject": "Welcome {{customer.first_name}}",
        "blocks_json": [
            {"type": "heading", "props": {"text": "Hi {{customer.first_name}}"}},
            {"type": "text", "props": {"html": "<p>Thanks for being a customer.</p>"}},
        ],
        "is_customer_facing": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return code


def _auth(token: str, tenant_id: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
        "Content-Type": "application/json",
    }


def _reset_rate(user_token: str, tenant_id: str) -> None:
    """Clear the caller's rate-limit bucket between asserts."""
    requests.post(
        f"{API}/comms/email-templates/_test-send-rate-reset",
        headers=_auth(user_token, tenant_id),
    )


def _test_send(user: dict, code: str, to: str | None = None):
    body = {} if to is None else {"to": to}
    return requests.post(
        f"{API}/comms/email-templates/{code}/test-send",
        headers=_auth(user["token"], user["tenant_id"]),
        json=body,
    )


# ══════════════════════════════════════════════════════════════════
# 1 · Admin + no `to` → sends to admin's own email.
# ══════════════════════════════════════════════════════════════════
def test_admin_without_to_sends_to_self(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    code = _seed_template(tenant_id)
    _reset_rate(admin["token"], tenant_id)
    r = _test_send(admin, code, to=None)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recipient"] == admin["email"]
    # Subject prefix invariant.
    assert body["subject"].startswith("[TEST] "), body
    # One corresponding send doc.
    doc = _sync.sends.find_one(
        {"tenant_id": tenant_id, "template_code": code, "kind": "test_send"},
    )
    assert doc is not None
    assert doc["recipient_email"] == admin["email"]


# ══════════════════════════════════════════════════════════════════
# 2 · Admin + `to` matching another tenant admin → 200.
# ══════════════════════════════════════════════════════════════════
def test_admin_with_tenant_peer_admin_recipient(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    peer = _seed_user(tenant_id, "super_admin")
    code = _seed_template(tenant_id)
    _reset_rate(admin["token"], tenant_id)
    r = _test_send(admin, code, to=peer["email"])
    assert r.status_code == 200, r.text
    assert r.json()["recipient"] == peer["email"]


# ══════════════════════════════════════════════════════════════════
# 3 · Admin + external arbitrary recipient → 400 not_allowed.
# ══════════════════════════════════════════════════════════════════
def test_admin_with_external_recipient_rejected(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    code = _seed_template(tenant_id)
    _reset_rate(admin["token"], tenant_id)
    r = _test_send(admin, code, to="attacker@evil.example")
    assert r.status_code == 400, r.text
    detail = (r.json() or {}).get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("code") == "test_recipient_not_allowed"


# ══════════════════════════════════════════════════════════════════
# 4 · Non-admin user → 403.
# ══════════════════════════════════════════════════════════════════
def test_non_admin_user_blocked(tenant_id):
    tech = _seed_user(tenant_id, "technician")
    code = _seed_template(tenant_id)
    r = _test_send(tech, code, to=None)
    assert r.status_code == 403, r.text


# ══════════════════════════════════════════════════════════════════
# 5 · Rate-limit — 11th call within one hour → 429 with Retry-After.
# ══════════════════════════════════════════════════════════════════
def test_rate_limit_11th_call_within_hour_returns_429(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    code = _seed_template(tenant_id)
    _reset_rate(admin["token"], tenant_id)
    # First 10 calls — all succeed.
    for i in range(10):
        r = _test_send(admin, code, to=None)
        assert r.status_code == 200, (i, r.text)
    # 11th — rate-limited.
    r = _test_send(admin, code, to=None)
    assert r.status_code == 429, r.text
    assert "retry-after" in {k.lower() for k in r.headers.keys()}, dict(r.headers)
    retry_after = int(r.headers["Retry-After"]) if "Retry-After" in r.headers \
        else int(r.headers["retry-after"])
    assert retry_after > 0


# ══════════════════════════════════════════════════════════════════
# 6 · Audit-trail invariants — kind="test_send" + [TEST] subject.
# ══════════════════════════════════════════════════════════════════
def test_audit_trail_stamps_kind_and_subject_prefix(tenant_id):
    admin = _seed_user(tenant_id, "admin")
    code = _seed_template(tenant_id)
    _reset_rate(admin["token"], tenant_id)
    r = _test_send(admin, code, to=None)
    assert r.status_code == 200, r.text
    docs = list(_sync.sends.find({"tenant_id": tenant_id, "template_code": code}))
    assert len(docs) == 1
    d = docs[0]
    # Kind is filterable out of the production send-history view.
    assert d["kind"] == "test_send"
    # Subject prefix is honored on the stored audit row too.
    assert d["subject"].startswith("[TEST] "), d["subject"]
    # Status is whatever Resend returns — "sent" when the key is
    # live, "not_sent_missing_key" / "mocked" / etc. otherwise.
    # Either way the audit row exists.
    assert d.get("status") is not None
    # requested_by_user_id links the test-send back to the admin.
    assert d["requested_by_user_id"] == admin["id"]
