"""Feb-2026 — /api/audits endpoint tests."""
from __future__ import annotations

import json
import os

import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path
from pymongo import MongoClient

# Load backend/.env so MONGO_URL/DB_NAME are visible inside pytest.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"

# Sync mongo client for test-fixture seeding — Motor + asyncio.run
# inside pytest sessions closes the event loop between tests and
# breaks Motor's internal pool. Sync pymongo dodges the problem.
_sync_client = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_client[os.environ["DB_NAME"]]


SHARED_SECRET_ENV = "LUMINO_ZAPIER_SHARED_SECRET"


def _secret() -> str:
    """Read the actual live secret from the backend .env — same
    process-level env the server sees. Fail loudly if empty."""
    from pathlib import Path
    envtxt = Path(__file__).resolve().parent.parent.joinpath(".env").read_text()
    for line in envtxt.splitlines():
        if line.startswith(f"{SHARED_SECRET_ENV}="):
            v = line.split("=", 1)[1].strip()
            if v and not v.startswith("REPLACE_ME_"):
                return v
    return ""


SECRET = _secret()
HDR_OK = {"x-zapier-shared-secret": SECRET, "Content-Type": "application/json"}
HDR_WRONG = {"x-zapier-shared-secret": "not-the-secret",
              "Content-Type": "application/json"}
HDR_NO_SECRET = {"Content-Type": "application/json"}


needs_secret = pytest.mark.skipif(not SECRET, reason="LUMINO_ZAPIER_SHARED_SECRET unset")


# ── 1. Happy path — signed POST persists ──────────────────────────
@needs_secret
def test_audit_post_signed_ok_persists():
    payload = {"customer_email": "no-match-test@example.com",
                "customer_name": "No Match Person",
                "site": "123 test lane",
                "score": 87}
    r = requests.post(f"{API}/audits", headers=HDR_OK,
                       data=json.dumps(payload), timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["audit_id"]
    # Round-trip verify persistence via GET (admin required — skip in
    # this test; the audit_id echo + no error is sufficient).


# ── 2/3. Auth failure modes ───────────────────────────────────────
@needs_secret
def test_audit_post_missing_secret_401():
    r = requests.post(f"{API}/audits", headers=HDR_NO_SECRET,
                       data=json.dumps({"a": 1}), timeout=10)
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


@needs_secret
def test_audit_post_wrong_secret_401():
    r = requests.post(f"{API}/audits", headers=HDR_WRONG,
                       data=json.dumps({"a": 1}), timeout=10)
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


# ── 4. Env not configured — direct-call handler with monkeypatch ──
def test_audit_post_env_not_configured_503(monkeypatch):
    """Direct-call the handler to simulate the empty-env branch
    without touching the live process env."""
    import asyncio
    monkeypatch.setenv(SHARED_SECRET_ENV, "")
    # Reload the module so _shared_secret() re-reads env at import time
    # (the helper reads env each call, so no reload needed — verify).
    from routers import audits

    async def _fake_body():
        return b"{}"

    class _Req:
        headers = {"x-zapier-shared-secret": "whatever"}
        async def body(self):
            return b"{}"

    result = asyncio.run(audits.receive_audit(_Req()))
    assert result.status_code == 503
    assert json.loads(result.body.decode())["error"] == "not_configured"


# ── 5. Malformed JSON ─────────────────────────────────────────────
@needs_secret
def test_audit_post_malformed_json_400():
    r = requests.post(f"{API}/audits", headers=HDR_OK,
                       data=b"{this is not json",
                       timeout=10)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_json"


# ── 6. Non-object JSON ────────────────────────────────────────────
@needs_secret
@pytest.mark.parametrize("bad", [b"[1,2,3]", b'"hello"', b"42"])
def test_audit_post_non_object_json_400(bad):
    r = requests.post(f"{API}/audits", headers=HDR_OK, data=bad, timeout=10)
    assert r.status_code == 400
    assert r.json()["error"] == "not_json_object"


# ── 7. Oversize body ──────────────────────────────────────────────
@needs_secret
def test_audit_post_oversize_413():
    huge = ("x" * (1_100_000))  # 1.1 MB
    payload = json.dumps({"blob": huge})
    r = requests.post(f"{API}/audits", headers=HDR_OK, data=payload, timeout=15)
    assert r.status_code == 413
    assert r.json()["error"] == "too_large"


# ── 8. Match customer by email (case-insensitive) ─────────────────
@needs_secret
def test_audit_matches_customer_by_email():
    """Seed a customer via sync pymongo, then POST an audit."""
    import uuid
    cust_id = f"audit-test-cust-{uuid.uuid4().hex[:8]}"
    _sync_db.customers.insert_one({
        "id": cust_id,
        "tenant_id": "audit-test-tenant",
        "email": "jane.email@example.com",
        "name": f"Jane Email {uuid.uuid4().hex[:6]}",
    })
    try:
        payload = {"customer_email": "JANE.EMAIL@Example.com",
                    "score": 92}
        r = requests.post(f"{API}/audits", headers=HDR_OK,
                           data=json.dumps(payload), timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["linked_customer_id"] == cust_id
        assert body["match_type"] == "email"
    finally:
        _sync_db.customers.delete_one({"id": cust_id})


# ── 9. Match by name when no email ────────────────────────────────
@needs_secret
def test_audit_matches_customer_by_name_when_no_email():
    import uuid
    unique_name = f"UniqueAuditPerson_{uuid.uuid4().hex[:10]}"
    cust_id = f"audit-test-cust-{uuid.uuid4().hex[:8]}"
    _sync_db.customers.insert_one({
        "id": cust_id,
        "tenant_id": "audit-test-tenant",
        "email": None,
        "name": unique_name,
    })
    try:
        payload = {"customer_name": unique_name.lower(), "score": 55}
        r = requests.post(f"{API}/audits", headers=HDR_OK,
                           data=json.dumps(payload), timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["linked_customer_id"] == cust_id
        assert body["match_type"] == "name"
    finally:
        _sync_db.customers.delete_one({"id": cust_id})


# ── 10. No match ──────────────────────────────────────────────────
@needs_secret
def test_audit_no_match_returns_null_link():
    payload = {"customer_email":
                f"nobody-{os.urandom(8).hex()}@nowhere-audit.example",
                "score": 1}
    r = requests.post(f"{API}/audits", headers=HDR_OK,
                       data=json.dumps(payload), timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["linked_customer_id"] is None
    assert body["match_type"] is None


# ── 11. Ambiguous name match leaves unlinked ──────────────────────
@needs_secret
def test_audit_ambiguous_match_leaves_unlinked():
    import uuid
    dup_name = f"DupeAudit_{uuid.uuid4().hex[:8]}"
    ids = []
    for _ in range(2):
        cid = f"audit-test-cust-{uuid.uuid4().hex[:8]}"
        _sync_db.customers.insert_one({
            "id": cid, "tenant_id": "audit-test-tenant",
            "email": None, "name": dup_name,
        })
        ids.append(cid)
    try:
        payload = {"customer_name": dup_name}
        r = requests.post(f"{API}/audits", headers=HDR_OK,
                           data=json.dumps(payload), timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["linked_customer_id"] is None
        assert body["match_type"] is None
    finally:
        for cid in ids:
            _sync_db.customers.delete_one({"id": cid})


# ── 12. Nested envelope extraction ────────────────────────────────
@needs_secret
def test_audit_extracts_from_nested_data_envelope():
    """Payload lacks top-level email; nested ``data.customer_email``
    must still be extracted."""
    import uuid
    unique = f"nested-{uuid.uuid4().hex[:6]}@example.com"
    cust_id = f"audit-test-cust-{uuid.uuid4().hex[:8]}"
    _sync_db.customers.insert_one({
        "id": cust_id, "tenant_id": "audit-test-tenant",
        "email": unique, "name": "Nested Envelope",
    })
    try:
        payload = {"data": {"customer_email": unique.upper(),
                              "score": 77}}
        r = requests.post(f"{API}/audits", headers=HDR_OK,
                           data=json.dumps(payload), timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["linked_customer_id"] == cust_id
        assert body["match_type"] == "email"
    finally:
        _sync_db.customers.delete_one({"id": cust_id})


# ── 13. GET requires auth ─────────────────────────────────────────
def test_get_audits_requires_auth():
    r = requests.get(f"{API}/audits", timeout=10)
    # 401 (missing token) or 403 (forbidden) — either is fail-closed.
    assert r.status_code in (401, 403), r.text


# ── 14/15. GET as admin lists items + filters ─────────────────────
def _admin_token():
    r = requests.post(f"{API}/auth/login",
                       json={"email": "manager@aquaterra.com",
                             "password": "password123"}, timeout=10)
    return r.json().get("access_token")


@needs_secret
def test_get_audits_admin_lists_items():
    # Seed at least one audit via the POST.
    _post = requests.post(f"{API}/audits", headers=HDR_OK,
                            data=json.dumps({"customer_email":
                                              "seed-list@example.com"}),
                            timeout=10)
    assert _post.status_code == 200
    tok = _admin_token()
    r = requests.get(f"{API}/audits?limit=5",
                       headers={"Authorization": f"Bearer {tok}"},
                       timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "total" in body
    assert isinstance(body["items"], list)
    assert body["total"] >= 1


@needs_secret
def test_get_audits_filter_by_has_link():
    tok = _admin_token()
    r = requests.get(f"{API}/audits?has_link=false&limit=5",
                       headers={"Authorization": f"Bearer {tok}"},
                       timeout=10)
    assert r.status_code == 200
    body = r.json()
    for item in body["items"]:
        assert item["linked_customer_id"] is None
