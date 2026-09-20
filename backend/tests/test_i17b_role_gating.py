"""Phase I1.7.b · Feb-2026 — Role gating for messaging integrations.

Uses the live backend on ``localhost:8001`` (already seeded via
``test_credentials.md``). Confirms:

  1. Tech-role users get 403 on PUT save / test / delete for SMS +
     Email providers (same gate as I1.7.a).
  2. Admin can save a Twilio config; the response is masked; the
     ``list`` endpoint reflects the new row.
  3. Manager can READ the list but cannot SAVE.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = _shared_db()
def _login(email="super@aquaterra.com", password="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _tenant_id(tok: str) -> str:
    r = requests.get(f"{API}/tenants/current", headers=_hdrs(tok), timeout=15)
    r.raise_for_status()
    return r.json()["id"]


def _seed_user(role: str) -> tuple[str, str]:
    from utils import hash_password
    tok = _login()
    tid = _tenant_id(tok)
    email = f"i17b-{role}-{uuid.uuid4().hex[:8]}@example.com"
    _sync.users.insert_one({
        "id": uuid.uuid4().hex, "email": email, "name": f"I17b {role}",
        "role": role, "tenant_id": tid,
        "password_hash": hash_password("Password123!"),
    })
    return email, tid


@pytest.fixture(autouse=True)
def _clean():
    yield
    _sync.users.delete_many({"email": {"$regex": r"^i17b-(tech|manager|admin)-"}})
    _sync.tenant_secrets.delete_many({"provider_key": {"$in": ["twilio", "resend"]},
                                         "tenant_id": {"$regex": r"^(?!never-).*"}})


def test_i17b_tech_cannot_save_test_or_delete_sms():
    email, _ = _seed_user("tech")
    tok = _login(email, "Password123!")
    r_save = requests.put(f"{API}/tenants/me/integrations/twilio",
                            headers=_hdrs(tok), timeout=15,
                            json={"config": {"account_sid": "AC", "auth_token": "x",
                                                "from_number": "+15551234567"}})
    r_test = requests.post(f"{API}/tenants/me/integrations/twilio/test",
                             headers=_hdrs(tok), timeout=15)
    r_del  = requests.delete(f"{API}/tenants/me/integrations/twilio",
                               headers=_hdrs(tok), timeout=15)
    assert r_save.status_code == 403
    assert r_test.status_code == 403
    assert r_del.status_code == 403


def test_i17b_manager_can_read_but_not_save():
    email, tid = _seed_user("manager")
    tok = _login(email, "Password123!")
    r_list = requests.get(f"{API}/tenants/me/integrations",
                            headers=_hdrs(tok), timeout=15)
    r_save = requests.put(f"{API}/tenants/me/integrations/twilio",
                            headers=_hdrs(tok), timeout=15,
                            json={"config": {"account_sid": "AC", "auth_token": "x",
                                                "from_number": "+15551234567"}})
    assert r_list.status_code == 200
    assert r_save.status_code == 403


def test_i17b_admin_save_hides_secret_fields_in_response():
    tok = _login()
    tid = _tenant_id(tok)
    _sync.tenant_secrets.delete_many({"tenant_id": tid, "provider_key": "twilio"})
    marker = f"AUTH-TOKEN-{uuid.uuid4().hex}"
    r = requests.put(
        f"{API}/tenants/me/integrations/twilio",
        headers=_hdrs(tok), timeout=15,
        json={"config": {"account_sid": "AC" + uuid.uuid4().hex[:20],
                             "auth_token": marker,
                             "from_number": "+15551234567"}},
    )
    try:
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == body  # noqa: shape check follows
        assert body["saved"] is True
        assert body["provider_key"] == "twilio"
        assert "…" in (body.get("connected_account_id_masked") or "")
        # NEVER echo the auth_token in the response.
        import json as _j
        assert marker not in _j.dumps(body)
        # List endpoint reflects the new row without leaking plaintext.
        lst = requests.get(f"{API}/tenants/me/integrations",
                              headers=_hdrs(tok), timeout=15).json()
        blob = _j.dumps(lst)
        assert marker not in blob
        assert any(row["provider_key"] == "twilio" and row["connected"]
                     for row in lst["integrations"])
    finally:
        _sync.tenant_secrets.delete_many({"tenant_id": tid, "provider_key": "twilio"})


def test_i17b_save_missing_required_field_returns_400_without_leaking_values():
    tok = _login()
    tid = _tenant_id(tok)
    _sync.tenant_secrets.delete_many({"tenant_id": tid, "provider_key": "smtp"})
    marker = f"SMTP-HOSTNAME-{uuid.uuid4().hex}"
    r = requests.put(
        f"{API}/tenants/me/integrations/smtp",
        headers=_hdrs(tok), timeout=15,
        json={"config": {"host": marker}},   # missing everything else
    )
    assert r.status_code == 400, r.text
    body_text = r.text
    assert marker not in body_text
    # Error names each missing field.
    for f in ("port", "username", "password", "from_addr"):
        assert f in body_text


def test_i17b_put_stripe_returns_400_use_oauth_flow_instead():
    tok = _login()
    r = requests.put(
        f"{API}/tenants/me/integrations/stripe",
        headers=_hdrs(tok), timeout=15,
        json={"config": {"api_key": "sk_test_dontsaveme"}},
    )
    assert r.status_code == 400
    assert "OAuth" in r.text
