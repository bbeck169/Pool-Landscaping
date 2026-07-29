"""Phase SEO-B · Feb-2026 — Backlink outreach CRM tests.

Live-server pattern (same as ``test_moderation_bulk.py`` +
``test_seo_scanner.py``). Talks to the running backend at
``BACKEND_API_URL`` / ``REACT_APP_BACKEND_URL``.

Covers:
* CRUD on prospects + templates.
* Template variable rendering via the send flow.
* Send flow flips prospect status → "contacted" + sets last_activity_at.
* CSV bulk-import (create + update + skip).
* RBAC — customer + technician blocked; manager+ allowed.
* Cross-tenant isolation (super_admin acting via X-Tenant-Slug).
* Pipeline counts.
"""
from __future__ import annotations

import io
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)

_TENANT_SLUG = "aquaterra"
_TAG = "seob-smoke"  # every doc created here is tagged for cleanup


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _headers(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}",
            "X-Tenant-Slug": _TENANT_SLUG}


def _super_h(): return _headers("super@aquaterra.com")
def _customer_h(): return _headers("customer@aquaterra.com")
def _tech_h():
    tech = _sync.users.find_one({"role": "technician",
                                  "email": {"$exists": True, "$ne": None}})
    return _headers(tech["email"])


@pytest.fixture
def clean_db():
    """Purge anything this suite created before + after."""
    _sync.outreach_prospects.delete_many({"tags": _TAG})
    _sync.outreach_templates.delete_many({"name": {"$regex": r"^seob-"}})
    _sync.outreach_messages.delete_many({"subject_rendered": {"$regex": r"seob-"}})
    yield
    _sync.outreach_prospects.delete_many({"tags": _TAG})
    _sync.outreach_templates.delete_many({"name": {"$regex": r"^seob-"}})
    _sync.outreach_messages.delete_many({"subject_rendered": {"$regex": r"seob-"}})


# ═══════════════════════ Prospect CRUD ══════════════════════════════

def _mk_prospect(**over) -> dict:
    body = {
        "domain": f"acme-{uuid.uuid4().hex[:8]}.com",
        "contact_name": "Alex Editor",
        "contact_email": f"alex+{uuid.uuid4().hex[:6]}@example.com",
        "contact_role": "editor",
        "target_page_url": "https://theirsite.com/best-pools",
        "desired_anchor": "pool service phoenix",
        "our_page_url": "https://ourpools.com/",
        "tags": [_TAG, "phoenix"],
        "notes": "",
        "status": "pending",
    }
    body.update(over)
    return body


def test_create_prospect_normalizes_domain(clean_db):
    r = requests.post(f"{API}/outreach/prospects",
                       json=_mk_prospect(domain="HTTPS://WWW.Acme.COM/blog"),
                       headers=_super_h(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["domain"] == "acme.com"
    assert body["status"] == "pending"
    assert body["contact_email"].endswith("@example.com")


def test_list_and_filter(clean_db):
    for s in ("pending", "contacted", "replied"):
        requests.post(f"{API}/outreach/prospects",
                        json=_mk_prospect(status=s),
                        headers=_super_h(), timeout=15)
    r = requests.get(f"{API}/outreach/prospects?status=contacted",
                      headers=_super_h(), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert all(x["status"] == "contacted" for x in body["items"])
    assert body["total"] >= 1


def test_patch_prospect(clean_db):
    r = requests.post(f"{API}/outreach/prospects",
                       json=_mk_prospect(), headers=_super_h(),
                       timeout=15)
    pid = r.json()["id"]
    r2 = requests.patch(f"{API}/outreach/prospects/{pid}",
                         json={"status": "replied",
                                "notes": "They said yes!"},
                         headers=_super_h(), timeout=15)
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "replied"
    assert body["notes"] == "They said yes!"


def test_soft_delete_hides_from_list(clean_db):
    r = requests.post(f"{API}/outreach/prospects",
                       json=_mk_prospect(), headers=_super_h(),
                       timeout=15)
    pid = r.json()["id"]
    dr = requests.delete(f"{API}/outreach/prospects/{pid}",
                          headers=_super_h(), timeout=15)
    assert dr.status_code == 200
    lst = requests.get(f"{API}/outreach/prospects",
                        headers=_super_h(), timeout=15).json()
    assert not any(x["id"] == pid for x in lst["items"])


# ═══════════════════════ Templates ══════════════════════════════════

def test_template_extracts_variables(clean_db):
    body = {
        "name": "seob-outreach-intro",
        "subject": "Quick note about {{their_domain}}",
        "body_html": (
            "Hi {{contact_name}}, would you consider linking to "
            "{{our_page_url}} with anchor {{desired_anchor}}?"),
    }
    r = requests.post(f"{API}/outreach/templates",
                       json=body, headers=_super_h(), timeout=15)
    assert r.status_code == 200, r.text
    v = r.json()
    assert set(v["variables"]) == {
        "contact_name", "their_domain", "our_page_url", "desired_anchor"}


def test_template_archive(clean_db):
    r = requests.post(f"{API}/outreach/templates",
                       json={"name": "seob-archive-me",
                              "subject": "s", "body_html": "b"},
                       headers=_super_h(), timeout=15).json()
    d = requests.delete(f"{API}/outreach/templates/{r['id']}",
                         headers=_super_h(), timeout=15)
    assert d.status_code == 200
    lst = requests.get(f"{API}/outreach/templates",
                        headers=_super_h(), timeout=15).json()
    assert not any(t["id"] == r["id"] for t in lst["items"])


# ═══════════════════════ Send flow ══════════════════════════════════

def test_send_renders_variables_and_flips_status(clean_db):
    tpl = requests.post(f"{API}/outreach/templates",
                         json={"name": "seob-send",
                                "subject": "seob- test to {{their_domain}}",
                                "body_html":
                                    "Hi {{contact_name}}, please link {{our_page_url}}"},
                         headers=_super_h(), timeout=15).json()
    p = requests.post(f"{API}/outreach/prospects",
                       json=_mk_prospect(domain="example-target.com",
                                            contact_name="Jamie",
                                            our_page_url="https://ourpools.com/best"),
                       headers=_super_h(), timeout=15).json()

    r = requests.post(
        f"{API}/outreach/prospects/{p['id']}/send",
        json={"template_id": tpl["id"]},
        headers=_super_h(), timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    # Even if Resend key is missing, a message row is created with
    # status="failed" and the prospect is still updated.
    msg = body["message"]
    assert "example-target.com" in msg["subject_rendered"]
    assert "Jamie" in msg["body_rendered"]
    assert "https://ourpools.com/best" in msg["body_rendered"]
    assert body["status"] in ("sent", "failed")

    # Prospect flipped to contacted (was pending).
    fresh = requests.get(f"{API}/outreach/prospects/{p['id']}",
                          headers=_super_h(), timeout=15).json()
    assert fresh["status"] == "contacted"
    assert fresh["last_activity_at"] is not None
    assert fresh["next_followup_at"] is not None
    # Messages timeline includes the send.
    tl = requests.get(
        f"{API}/outreach/prospects/{p['id']}/messages",
        headers=_super_h(), timeout=15).json()
    assert tl["total"] == 1


def test_send_requires_contact_email(clean_db):
    tpl = requests.post(f"{API}/outreach/templates",
                         json={"name": "seob-noemail",
                                "subject": "x", "body_html": "y"},
                         headers=_super_h(), timeout=15).json()
    # Post a prospect w/o email.
    r = requests.post(f"{API}/outreach/prospects",
                       json={**_mk_prospect(),
                              "contact_email": None},
                       headers=_super_h(), timeout=15)
    pid = r.json()["id"]
    r2 = requests.post(f"{API}/outreach/prospects/{pid}/send",
                        json={"template_id": tpl["id"]},
                        headers=_super_h(), timeout=15)
    assert r2.status_code == 400
    assert "no_contact_email" in r2.text


# ═══════════════════════ CSV import ═════════════════════════════════

_CSV = (
    "domain,contact_name,contact_email,contact_role,tags,notes\n"
    "seob-csv-alpha.com,Ada,ada@seob-csv-alpha.com,editor,seob-smoke,seed-1\n"
    "seob-csv-beta.com,Barry,barry@seob-csv-beta.com,marketing,seob-smoke,seed-2\n"
    "seob-csv-alpha.com,Ada,ada@seob-csv-alpha.com,editor,seob-smoke,dup-check\n"
    ",,,,seob-smoke,\n"  # skipped (missing domain)
)


def test_csv_bulk_import(clean_db):
    files = {"file": ("prospects.csv", _CSV, "text/csv")}
    r = requests.post(f"{API}/outreach/prospects/bulk-import",
                       files=files, headers=_super_h(), timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2
    assert body["updated"] == 1  # duplicate row → update path
    assert body["skipped"] == 1  # missing domain
    # Confirm rows landed.
    lst = requests.get(f"{API}/outreach/prospects?search=seob-csv",
                        headers=_super_h(), timeout=15).json()
    domains = {x["domain"] for x in lst["items"]}
    assert "seob-csv-alpha.com" in domains
    assert "seob-csv-beta.com" in domains


def test_csv_dry_run_does_not_persist(clean_db):
    files = {"file": ("prospects.csv", _CSV, "text/csv")}
    r = requests.post(
        f"{API}/outreach/prospects/bulk-import?dry_run=true",
        files=files, headers=_super_h(), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    # Preview populated but no rows in DB.
    lst = requests.get(f"{API}/outreach/prospects?search=seob-csv",
                        headers=_super_h(), timeout=15).json()
    assert lst["total"] == 0


# ═══════════════════════ RBAC ═══════════════════════════════════════

def test_customer_forbidden(clean_db):
    r = requests.get(f"{API}/outreach/prospects",
                      headers=_customer_h(), timeout=15)
    assert r.status_code == 403


def test_technician_forbidden(clean_db):
    r = requests.get(f"{API}/outreach/prospects",
                      headers=_tech_h(), timeout=15)
    assert r.status_code == 403


# ═══════════════════════ Cross-tenant isolation ═════════════════════

def test_cross_tenant_isolation(clean_db):
    """Data in another tenant must be invisible to the caller.

    We directly seed a prospect under the ``sunbelt`` tenant, then
    verify super@aquaterra (whose effective tenant_id resolves to
    aquaterra) gets a 404, not a 200.
    """
    other = _sync.tenants.find_one({"slug": "sunbelt"})
    if not other:
        pytest.skip("sunbelt tenant missing")
    pid = str(uuid.uuid4())
    _sync.outreach_prospects.insert_one({
        "id": pid, "tenant_id": other["id"],
        "created_by_user_id": "seed", "created_at": "2026-02-01T00:00:00Z",
        "domain": "seob-crosstenant.com",
        "contact_name": "X", "contact_email": "x@seob-crosstenant.com",
        "contact_role": "editor",
        "target_page_url": None, "desired_anchor": None,
        "our_page_url": None,
        "tags": [_TAG], "notes": "", "status": "pending",
        "last_activity_at": None, "next_followup_at": None,
        "updated_at": "2026-02-01T00:00:00Z", "deleted_at": None,
    })
    r = requests.get(f"{API}/outreach/prospects/{pid}",
                      headers=_super_h(), timeout=15)
    assert r.status_code == 404, r.text
    # It also must not appear in the list.
    lst = requests.get(f"{API}/outreach/prospects?search=seob-crosstenant",
                        headers=_super_h(), timeout=15).json()
    assert not any(x["id"] == pid for x in lst["items"])


# ═══════════════════════ Pipeline counts ════════════════════════════

def test_pipeline_counts(clean_db):
    for s in ("pending", "pending", "contacted", "replied",
                "link_placed", "declined"):
        requests.post(f"{API}/outreach/prospects",
                        json=_mk_prospect(status=s),
                        headers=_super_h(), timeout=15)
    r = requests.get(f"{API}/outreach/pipeline",
                      headers=_super_h(), timeout=15)
    assert r.status_code == 200
    counts = r.json()
    assert counts["pending"] >= 2
    assert counts["contacted"] >= 1
    assert counts["replied"] >= 1
    assert counts["link_placed"] >= 1
    assert counts["declined"] >= 1
    assert counts["total"] >= 6


# ═══════════════════════ Followups + digest cron ════════════════════

def test_followups_and_manual_digest(clean_db):
    # Seed a prospect due yesterday.
    tid = _sync.tenants.find_one({"slug": _TENANT_SLUG})["id"]
    pid = str(uuid.uuid4())
    _sync.outreach_prospects.insert_one({
        "id": pid, "tenant_id": tid,
        "created_by_user_id": "seed", "created_at": "2026-02-01T00:00:00Z",
        "domain": "seob-followup.com",
        "contact_name": "Follow", "contact_email": "f@seob-followup.com",
        "contact_role": "editor", "target_page_url": None,
        "desired_anchor": None, "our_page_url": None,
        "tags": [_TAG], "notes": "",
        "status": "contacted",
        "last_activity_at": "2026-02-01T00:00:00Z",
        "next_followup_at": "2026-02-02T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
        "deleted_at": None,
    })
    # Due list must include it.
    r = requests.get(f"{API}/outreach/followups", headers=_super_h(),
                      timeout=15)
    assert r.status_code == 200
    assert any(x["id"] == pid for x in r.json()["items"])
    # Manual cron trigger must complete without raising.
    r2 = requests.post(f"{API}/outreach/cron/followup-digest",
                        headers=_super_h(), timeout=30)
    assert r2.status_code == 200
    body = r2.json()
    assert body["tenants_scanned"] >= 1
    assert body["prospects_flagged"] >= 1
