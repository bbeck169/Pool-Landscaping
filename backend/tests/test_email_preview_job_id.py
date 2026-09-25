"""Feb-2026 · Visit-Email Preview · ``preview_job_id`` query param.

Locks the contract for the branded visit-summary preview branch
on ``GET /api/tenants/me/email-preview``:

  1. Admin passes ``preview_job_id`` for a job they own →
     200 with ``template="visit_summary"`` and branded HTML that
     contains job / tenant markers (title-card hero, POOL grid,
     etc.).
  2. Admin passes ``preview_job_id`` for a job owned by ANOTHER
     tenant → 404 (never leak across tenant boundary).
  3. Admin passes an unknown ``preview_job_id`` → 404.
  4. Admin omits ``preview_job_id`` → endpoint falls back to the
     ``template`` stub (existing behavior stays intact).

Runs against the live preview backend (mirrors the pattern used
by the sibling ``test_email_preview.py``).
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)

# Sync Mongo client — motor's async client is bound to the
# backend's event loop and can't be re-used from pytest's loop
# (see runtime "attached to a different loop" error). Fixtures
# below use this sync handle for read-only lookups + throw-away
# job inserts.
_MONGO_URL = os.environ.get("MONGO_URL")
_DB_NAME = os.environ.get("DB_NAME")
if not (_MONGO_URL and _DB_NAME):
    pytest.skip("MONGO_URL / DB_NAME not set", allow_module_level=True)
_sync_db = MongoClient(_MONGO_URL, serverSelectionTimeoutMS=3000)[_DB_NAME]

REQ_TIMEOUT = 30

# Aquaterra tenant — the admin fixture below owns it. Matches the
# tenant_id stamped on the seeded jobs / service reports.
_AQUATERRA_TENANT_ID = "affdfbfa-88b9-4baa-ae45-2ef78531b6e4"

# Cross-tenant sentinel — an ephemeral tenant id we scope the
# throw-away foreign job to.  Chosen so the id is guaranteed to
# NOT match aquaterra even in the unlikely case the seed is
# regenerated.
_FOREIGN_TENANT_ID = f"tenant-B-preview-{uuid.uuid4().hex[:8]}"


# ═════════════════════════════════════════════════════════════════
# Auth helpers
# ═════════════════════════════════════════════════════════════════
def _session(email: str, password: str) -> requests.Session:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code}")
    body = r.json()
    tok = body.get("access_token") or body.get("token")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="module")
def admin_sess() -> requests.Session:
    return _session("admin@aquaterra.com", "password123")


# ═════════════════════════════════════════════════════════════════
# Fixture: pick a seeded aquaterra pool job for the happy-path
# render.  We prefer a job with (readings + photos + property_id)
# so the branded HTML exercises the largest surface area.  Falls
# back to any tenant-owned job so the suite still runs on a
# reduced seed.
# ═════════════════════════════════════════════════════════════════
def _pick_aquaterra_job() -> str:
    """Return an aquaterra job_id whose service_report has at
    least one chemical reading (guarantees POOL grid renders).
    """
    best = None
    for sr in _sync_db.service_reports.find(
        {"tenant_id": _AQUATERRA_TENANT_ID,
         "chemical_readings": {"$exists": True, "$ne": []}},
        {"_id": 0, "job_id": 1, "chemical_readings": 1, "photos": 1},
    ):
        readings = sr.get("chemical_readings") or []
        photos = sr.get("photos") or []
        job = _sync_db.jobs.find_one(
            {"id": sr["job_id"], "tenant_id": _AQUATERRA_TENANT_ID},
            {"_id": 0, "id": 1, "property_id": 1},
        )
        if not job or not job.get("property_id"):
            continue
        if len(readings) >= 2 and len(photos) >= 1:
            return sr["job_id"]
        if best is None and len(readings) >= 2:
            best = sr["job_id"]
    if best:
        return best
    # Absolute fallback — any aquaterra job at all.
    j = _sync_db.jobs.find_one(
        {"tenant_id": _AQUATERRA_TENANT_ID}, {"_id": 0, "id": 1},
    )
    if not j:
        raise RuntimeError("no aquaterra jobs seeded")
    return j["id"]


@pytest.fixture(scope="module")
def owned_job_id() -> str:
    return _pick_aquaterra_job()


# ═════════════════════════════════════════════════════════════════
# Fixture: cross-tenant foreign job.  Inserted directly into Mongo
# with a synthetic tenant_id so it can NEVER match aquaterra.
# Cleaned up in teardown.
# ═════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def foreign_job_id():
    jid = f"foreign-job-{uuid.uuid4().hex[:12]}"
    _sync_db.jobs.insert_one({
        "id": jid,
        "tenant_id": _FOREIGN_TENANT_ID,
        "customer_id": "foreign-cust",
        "title": "Foreign tenant job — should not leak",
        "service_type": "pool_maintenance",
        "status": "scheduled",
        "address": "999 Foreign Ave, Nowhere, XX 00000",
    })
    try:
        yield jid
    finally:
        _sync_db.jobs.delete_one({"id": jid,
                                    "tenant_id": _FOREIGN_TENANT_ID})


# ═════════════════════════════════════════════════════════════════
# Tests
# ═════════════════════════════════════════════════════════════════
_URL = "/api/tenants/me/email-preview"
_HTML_RE = re.compile(r"<html\b", re.IGNORECASE)


def test_owned_job_renders_branded_visit_summary(
    admin_sess: requests.Session, owned_job_id: str,
):
    """Admin previews a tenant-owned job → 200 + branded HTML."""
    r = admin_sess.get(
        f"{BASE_URL}{_URL}"
        f"?template=quote_sent&preview_job_id={owned_job_id}",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Contract: the template override signals visit_summary render.
    assert body["template"] == "visit_summary", body
    assert body.get("preview_job_id") == owned_job_id
    html = body["html"]
    assert isinstance(html, str) and html
    # Full-document render (starts at <!DOCTYPE>) — one <html>.
    assert len(_HTML_RE.findall(html)) == 1, html[:200]
    # Portal-style branded card markers must be present.
    assert "SERVICE CHECKLIST" in html.upper() \
        or "POOL" in html.upper() \
        or "VISIT PHOTOS" in html.upper(), html[:2000]
    # Subject line follows the visit-summary shape.
    assert "service visit" in body["subject"].lower()
    # Plain-text sibling ships too so the caller can screenshot
    # either side.
    assert body.get("text"), body


def test_cross_tenant_job_id_returns_404(
    admin_sess: requests.Session, foreign_job_id: str,
):
    """Aquaterra admin can NOT preview a foreign tenant's job."""
    r = admin_sess.get(
        f"{BASE_URL}{_URL}"
        f"?template=quote_sent&preview_job_id={foreign_job_id}",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 404, r.text
    # The 404 body must not leak the foreign address string.
    assert "Foreign Ave" not in r.text


def test_unknown_job_id_returns_404(admin_sess: requests.Session):
    r = admin_sess.get(
        f"{BASE_URL}{_URL}"
        f"?template=quote_sent&preview_job_id=job-does-not-exist-xxx",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 404, r.text


def test_omitted_preview_job_id_falls_back_to_stub(
    admin_sess: requests.Session,
):
    """No ``preview_job_id`` → existing stub behavior unchanged."""
    r = admin_sess.get(
        f"{BASE_URL}{_URL}?template=quote_sent",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template"] == "quote_sent"
    assert "Review quote" in body["html"] \
        or "quote is ready" in body["html"]
    # Stub path does NOT surface preview_job_id in the response.
    assert "preview_job_id" not in body


def test_empty_preview_job_id_falls_back_to_stub(
    admin_sess: requests.Session,
):
    """Empty string param behaves like ``None`` — stub path."""
    r = admin_sess.get(
        f"{BASE_URL}{_URL}?template=quote_sent&preview_job_id=",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template"] == "quote_sent"


# ══════════════════════════════════════════════════════════════════
# Batch follow-up C · ``template`` is optional when the caller
# supplies ``preview_job_id`` — the branded visit-summary render
# is what they want, no stub involved.
# ══════════════════════════════════════════════════════════════════
def test_preview_job_id_alone_returns_200_with_visit_summary(
    admin_sess: requests.Session, owned_job_id: str,
):
    """``?preview_job_id=<seed_job>`` alone → 200, visit_summary."""
    r = admin_sess.get(
        f"{BASE_URL}{_URL}?preview_job_id={owned_job_id}",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template"] == "visit_summary"
    assert body.get("preview_job_id") == owned_job_id
    assert body.get("subject"), body
    assert body.get("html"), body
    assert body.get("text"), body


def test_no_template_and_no_preview_job_id_returns_400(
    admin_sess: requests.Session,
):
    """Neither param supplied → 400 with the actionable hint."""
    r = admin_sess.get(f"{BASE_URL}{_URL}", timeout=REQ_TIMEOUT)
    assert r.status_code == 400, r.text
    body_text = r.text.lower()
    assert "template" in body_text
    assert "preview_job_id" in body_text

