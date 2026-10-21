"""TD-90-search-address-gaps · Feb-2026.

Covers the jobs + leads bucket address-match expansion on
``GET /api/search``:

  * Jobs: ``title``, ``customer_name``, ``address`` (new).
  * Leads: ``name``, ``email``, ``phone``, ``address`` (new),
    ``service_address`` (new).

Existing non-address matches must still work (regression) and the hit
shape must stay ``{id, primary, secondary}``. FK-ladder resolution is
NOT in scope — matching is purely on persisted snapshots. RBAC gate,
soft-delete filter, closed-lead-status gate, and tenant isolation all
hold after the field-set change.
"""
from __future__ import annotations

import os
import uuid
from typing import Dict, List

import httpx
import pytest
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


BASE = "http://localhost:8001"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db() if (_MONGO_URL and _DB_NAME) else None


def _mk_tenant(prefix: str = "TEST_td90") -> str:
    tid = f"{prefix}_tenant_{uuid.uuid4().hex}"
    _sync.tenants.insert_one({
        "id": tid,
        "slug": f"td90-{uuid.uuid4().hex[:8]}",
        "name": "TD90 Tenant", "active": True,
    })
    return tid


def _mk_user(tid: str, role: str = "admin") -> str:
    from utils import hash_password
    email = f"td90-{role}-{uuid.uuid4().hex[:8]}@example.com"
    _sync.users.insert_one({
        "id": f"TEST_td90_user_{uuid.uuid4().hex}",
        "email": email, "role": role,
        "password_hash": hash_password("password123"),
        "tenant_id": tid, "name": f"TD90 {role}",
        "failed_login_attempts": 0, "active": True,
    })
    return email


def _login(email: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": email, "password": "password123",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _seed_job(tid: str, *, title: str = "", address: str = "",
              customer_name: str = "", status: str = "pending") -> str:
    jid = f"TEST_td90_job_{uuid.uuid4().hex}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "title": title, "address": address,
        "customer_name": customer_name, "status": status,
        "created_at": "2026-02-01T00:00:00+00:00",
    })
    return jid


def _seed_lead(tid: str, *, name: str = "", email: str = "",
                phone: str = "", address: str = "",
                service_address: str = "",
                status: str = "new") -> str:
    lid = f"TEST_td90_lead_{uuid.uuid4().hex}"
    _sync.leads.insert_one({
        "id": lid, "tenant_id": tid,
        "name": name, "email": email, "phone": phone,
        "address": address, "service_address": service_address,
        "status": status,
        "created_at": "2026-02-01T00:00:00+00:00",
    })
    return lid


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_ctx():
    tid = _mk_tenant()
    yield {"tid": tid, "token": _login(_mk_user(tid, "admin"))}


def _search(token: str, **params) -> Dict[str, List[dict]]:
    r = httpx.get(f"{BASE}/api/search", params=params,
                   headers=_auth(token), timeout=30)
    r.raise_for_status()
    return r.json()


# ──────────────────────────────────────────────────────────────────
# Jobs — address match
# ──────────────────────────────────────────────────────────────────
def test_jobs_address_substring_hit(admin_ctx):
    tid = admin_ctx["tid"]
    jid = _seed_job(tid, title="Routine Service",
                     address="8616 Preview St, Scottsdale AZ 85000")
    out = _search(admin_ctx["token"], q="Preview St",
                   entities="jobs", limit=5)
    hits = [h for h in out.get("jobs", []) if h["id"] == jid]
    assert len(hits) == 1
    # Hit shape unchanged — exactly 3 keys.
    assert set(hits[0].keys()) == {"id", "primary", "secondary"}
    assert hits[0]["primary"] == "Routine Service"


def test_jobs_address_case_insensitive(admin_ctx):
    tid = admin_ctx["tid"]
    jid = _seed_job(tid, title="Weekly Visit",
                     address="123 Camelback Rd")
    out = _search(admin_ctx["token"], q="CAMELBACK",
                   entities="jobs", limit=5)
    hits = [h for h in out["jobs"] if h["id"] == jid]
    assert len(hits) == 1


def test_jobs_zip_in_address_hit(admin_ctx):
    """Operator typing a zip code should match zip-appended address strings."""
    tid = admin_ctx["tid"]
    jid = _seed_job(tid, title="Winter Maintenance",
                     address="456 Oak Ln, Mesa AZ 85201")
    out = _search(admin_ctx["token"], q="85201",
                   entities="jobs", limit=5)
    hits = [h for h in out["jobs"] if h["id"] == jid]
    assert len(hits) == 1


# ──────────────────────────────────────────────────────────────────
# Jobs — regression on title + customer_name
# ──────────────────────────────────────────────────────────────────
def test_jobs_title_regression(admin_ctx):
    tid = admin_ctx["tid"]
    jid = _seed_job(tid, title="Spring Cleanup",
                     customer_name="Jane Smith",
                     address="")
    out = _search(admin_ctx["token"], q="Spring",
                   entities="jobs", limit=5)
    hits = [h for h in out["jobs"] if h["id"] == jid]
    assert len(hits) == 1


def test_jobs_customer_name_regression(admin_ctx):
    tid = admin_ctx["tid"]
    jid = _seed_job(tid, title="Visit",
                     customer_name="Alberto Rodriguez",
                     address="")
    out = _search(admin_ctx["token"], q="Alberto",
                   entities="jobs", limit=5)
    hits = [h for h in out["jobs"] if h["id"] == jid]
    assert len(hits) == 1


# ──────────────────────────────────────────────────────────────────
# Leads — address + service_address match
# ──────────────────────────────────────────────────────────────────
def test_leads_address_substring_hit(admin_ctx):
    tid = admin_ctx["tid"]
    lid = _seed_lead(tid, name="Lead One", status="new",
                      address="1 Preview Ln, Testville AZ 85000")
    out = _search(admin_ctx["token"], q="Testville",
                   entities="leads", limit=5)
    hits = [h for h in out.get("leads", []) if h["id"] == lid]
    assert len(hits) == 1
    assert hits[0]["primary"] == "Lead One"
    # Hit shape unchanged.
    assert set(hits[0].keys()) == {"id", "primary", "secondary"}


def test_leads_service_address_substring_hit(admin_ctx):
    """``service_address`` is the Google-Places autofill target — must match too."""
    tid = admin_ctx["tid"]
    lid = _seed_lead(tid, name="Autofill Lead", status="new",
                      address="",
                      service_address="22 Alternative Ave, Phoenix AZ")
    out = _search(admin_ctx["token"], q="Alternative Ave",
                   entities="leads", limit=5)
    hits = [h for h in out["leads"] if h["id"] == lid]
    assert len(hits) == 1


def test_leads_address_case_insensitive(admin_ctx):
    tid = admin_ctx["tid"]
    lid = _seed_lead(tid, name="CI Lead", status="contacted",
                      service_address="99 Example Rd")
    out = _search(admin_ctx["token"], q="EXAMPLE",
                   entities="leads", limit=5)
    hits = [h for h in out["leads"] if h["id"] == lid]
    assert len(hits) == 1


# ──────────────────────────────────────────────────────────────────
# Leads — regression on name + email + phone
# ──────────────────────────────────────────────────────────────────
def test_leads_name_regression(admin_ctx):
    tid = admin_ctx["tid"]
    lid = _seed_lead(tid, name="Carmen Verde", status="quoted")
    out = _search(admin_ctx["token"], q="Carmen",
                   entities="leads", limit=5)
    hits = [h for h in out["leads"] if h["id"] == lid]
    assert len(hits) == 1


def test_leads_email_regression(admin_ctx):
    tid = admin_ctx["tid"]
    unique = f"findme-{uuid.uuid4().hex[:6]}"
    lid = _seed_lead(tid, name="Email Lead", status="new",
                      email=f"{unique}@example.com")
    out = _search(admin_ctx["token"], q=unique,
                   entities="leads", limit=5)
    hits = [h for h in out["leads"] if h["id"] == lid]
    assert len(hits) == 1


# ──────────────────────────────────────────────────────────────────
# Closed-lead-status gate still holds
# ──────────────────────────────────────────────────────────────────
def test_leads_closed_won_with_matching_address_excluded(admin_ctx):
    """Closed-won leads must stay out of the dropdown even with address match."""
    tid = admin_ctx["tid"]
    _seed_lead(tid, name="Closed Won", status="closed_won",
                address="100 Closed St, Phoenix AZ")
    out = _search(admin_ctx["token"], q="Closed St",
                   entities="leads", limit=5)
    assert out["leads"] == []


# ──────────────────────────────────────────────────────────────────
# RBAC — field tech still 403s after the field-set change
# ──────────────────────────────────────────────────────────────────
def test_rbac_field_tech_still_403():
    tid = _mk_tenant("TEST_td90_rbac")
    tok = _login(_mk_user(tid, role="technician"))
    _seed_job(tid, title="any", address="any address")
    r = httpx.get(f"{BASE}/api/search",
                   params={"q": "address", "entities": "jobs"},
                   headers=_auth(tok), timeout=30)
    assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────
# Soft-delete still excludes jobs with matching addresses
# ──────────────────────────────────────────────────────────────────
def test_jobs_soft_delete_excluded(admin_ctx):
    tid = admin_ctx["tid"]
    jid = f"TEST_td90_job_{uuid.uuid4().hex}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "title": "Deleted Job",
        "address": "999 Gone Rd, Phoenix AZ",
        "status": "pending",
        "deleted_at": "2026-02-01T00:00:00+00:00",
    })
    out = _search(admin_ctx["token"], q="Gone Rd",
                   entities="jobs", limit=5)
    assert out["jobs"] == []


# ──────────────────────────────────────────────────────────────────
# Tenant isolation preserved
# ──────────────────────────────────────────────────────────────────
def test_tenant_isolation_on_address_match(admin_ctx):
    other_tid = _mk_tenant("TEST_td90_other")
    _seed_job(other_tid, title="OtherTenant Job",
                address="333 Isolated Blvd")
    out = _search(admin_ctx["token"], q="Isolated Blvd",
                   entities="jobs", limit=5)
    assert out["jobs"] == []
