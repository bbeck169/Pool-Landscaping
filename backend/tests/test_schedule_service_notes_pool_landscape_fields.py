"""Phase 3 · Feb-2026 — ``service_notes_pool`` + ``service_notes_landscape``
backend contract (integration test).

Locks the two additive customer-sourced note fields that the schedule
job card consumes:

  * ``GET /api/schedule/today`` — ``items[*].service_notes_pool`` and
    ``service_notes_landscape`` are both present on every job item.
    Values mirror ``customer.service_notes.{pool,landscape}`` and are
    independent of the job's ``service_type``.  Legacy
    ``service_note`` (single-resolved) continues to exist unchanged.

  * ``GET /api/jobs`` — same two fields are present on every job
    document (hit AND miss branches — both populated or both ``None``
    when the customer link is missing).

Also exercises an "empty service_notes" path so the FE never has to
defensively coalesce ``undefined``.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} => {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def seeded(admin_headers):
    """Create a customer with BOTH pool + landscape service notes
    populated, plus a scheduled job for today assigned to the admin
    user so ``/schedule/today`` surfaces the row."""
    marker = uuid.uuid4().hex[:8]
    c = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"Phase3SvcNotes {marker}",
        "first_name": "TEST_P3",
        "last_name": f"SvcNotes{marker}",
        "email": f"p3_{marker}@example.com",
        "phone": "+14805559300",
    }, timeout=15)
    assert c.status_code in (200, 201), c.text
    customer = c.json()
    cid = customer["id"]

    # Seed BOTH pool + landscape notes on the customer.
    patch = requests.patch(
        f"{API}/customers/{cid}/service-notes",
        headers=admin_headers,
        json={"pool":      "Muriatic on-site — no MAP · drain pre-shock",
              "landscape": "Palm fronds in NW corner · haul with crew"},
        timeout=15,
    )
    assert patch.status_code == 200, patch.text

    # Create a scheduled job for today for this customer.
    from datetime import datetime, timezone
    today_iso = datetime.now(timezone.utc).date().isoformat()
    me = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=15)
    assert me.status_code == 200, me.text
    admin_uid = me.json().get("id")
    j = requests.post(f"{API}/jobs", headers=admin_headers, json={
        "title":          "Phase 3 service-notes smoke",
        "customer_id":    cid,
        "customer_name":  customer.get("name"),
        "service_type":   "Pool Cleaning",
        "work_class":     "service",
        "scheduled_date": today_iso,
        "status":         "scheduled",
        "technician_id":  admin_uid,
    }, timeout=15)
    assert j.status_code in (200, 201), j.text
    job = j.json()

    yield {"customer": customer, "job": job}

    # Cleanup — delete the job first (FK-free, but keeps the admin's
    # schedule view clean for subsequent runs) then the customer.
    try:
        requests.delete(f"{API}/jobs/{job['id']}", headers=admin_headers, timeout=15)
    finally:
        requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)


# ──────────────────────────────────────────────────────────────────
#  /api/schedule/today — assert both fields on every item
# ──────────────────────────────────────────────────────────────────

def test_schedule_today_exposes_pool_and_landscape_notes(
        admin_headers, seeded):
    """``/schedule/today`` serializer returns BOTH ``service_notes_pool``
    and ``service_notes_landscape`` on every job item regardless of
    the job's own ``service_type``."""
    r = requests.get(f"{API}/schedule/today", headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    payload = r.json()
    # ``/schedule/today`` returns ``{"items": [...]}``.
    items = payload.get("items") if isinstance(payload, dict) else payload
    assert isinstance(items, list) and items, (
        f"expected non-empty items list; got {type(items).__name__}: {items!r}"
    )
    # Every item must carry both fields (null allowed; ``undefined`` not).
    for it in items:
        assert "service_notes_pool"      in it, (
            f"item missing service_notes_pool: {it.get('id')}"
        )
        assert "service_notes_landscape" in it, (
            f"item missing service_notes_landscape: {it.get('id')}"
        )
    # Our seeded job surfaces with the exact populated notes.
    jid = seeded["job"]["id"]
    mine = [it for it in items if it.get("id") == jid]
    assert mine, f"seeded job {jid} not in schedule/today items"
    me = mine[0]
    assert me["service_notes_pool"].startswith("Muriatic on-site"), me
    assert me["service_notes_landscape"].startswith("Palm fronds"),  me
    # Legacy single-resolved field still populated (regression guard
    # for the additive-only contract).
    assert "service_note" in me, "legacy service_note must be preserved"


# ──────────────────────────────────────────────────────────────────
#  /api/jobs — same two fields, hit + miss branches
# ──────────────────────────────────────────────────────────────────

def test_jobs_list_exposes_pool_and_landscape_notes(admin_headers, seeded):
    """``GET /api/jobs`` enrichment surfaces the pool + landscape
    notes under the same additive keys as ``/schedule/today``."""
    cid = seeded["customer"]["id"]
    r = requests.get(f"{API}/jobs?customer_id={cid}",
                     headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    docs = body.get("items") if isinstance(body, dict) else body
    assert isinstance(docs, list) and docs, (
        f"expected non-empty jobs list; got {type(docs).__name__}"
    )
    # Spot-check our seeded job.
    jid = seeded["job"]["id"]
    mine = [d for d in docs if d.get("id") == jid]
    assert mine, f"seeded job {jid} missing from /jobs"
    me = mine[0]
    assert me.get("service_notes_pool", "").startswith("Muriatic on-site"), me
    assert me.get("service_notes_landscape", "").startswith("Palm fronds"), me
    # Field shape contract — every returned doc for this customer has
    # the keys (null OK).
    for d in docs:
        assert "service_notes_pool"      in d, f"missing on {d.get('id')}"
        assert "service_notes_landscape" in d, f"missing on {d.get('id')}"


# ──────────────────────────────────────────────────────────────────
#  Empty / missing service_notes — both fields render as ``None``
# ──────────────────────────────────────────────────────────────────

def test_empty_service_notes_renders_as_none(admin_headers):
    """A customer with NO ``service_notes`` field returns ``None``
    on both pool + landscape slots so the FE doesn't need defensive
    ``?? null`` coalescing."""
    marker = uuid.uuid4().hex[:8]
    c = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"Phase3EmptyNotes {marker}",
        "first_name": "TEST_P3E",
        "last_name": f"Empty{marker}",
        "phone": "+14805559310",
    }, timeout=15)
    assert c.status_code in (200, 201), c.text
    customer = c.json()
    cid = customer["id"]
    try:
        from datetime import datetime, timezone
        today_iso = datetime.now(timezone.utc).date().isoformat()
        j = requests.post(f"{API}/jobs", headers=admin_headers, json={
            "title":          "Phase 3 empty-notes smoke",
            "customer_id":    cid,
            "customer_name":  customer.get("name"),
            "service_type":   "Pool Cleaning",
            "scheduled_date": today_iso,
            "status":         "scheduled",
        }, timeout=15)
        assert j.status_code in (200, 201), j.text
        job = j.json()
        jid = job["id"]
        try:
            r = requests.get(f"{API}/jobs?customer_id={cid}",
                             headers=admin_headers, timeout=20)
            assert r.status_code == 200
            body = r.json()
            docs = body.get("items") if isinstance(body, dict) else body
            mine = [d for d in docs if d.get("id") == jid]
            assert mine, f"job {jid} missing"
            me = mine[0]
            # Explicit ``None`` — never ``KeyError`` on the FE side.
            assert me.get("service_notes_pool",      "sentinel") is None, me
            assert me.get("service_notes_landscape", "sentinel") is None, me
        finally:
            requests.delete(f"{API}/jobs/{jid}", headers=admin_headers, timeout=15)
    finally:
        requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)
