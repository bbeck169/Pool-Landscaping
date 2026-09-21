"""Phase LD1 → Phase P6 · Feb 2026 — Leads bulk HARD delete.

Reconciled Option-B contract:

Response envelope:
    {
        "requested": <int>,
        "deleted":   <int>,
        "skipped":   [{"lead_id": "...", "code": <c>}, ...],
        "bulk_op_id": "<uuid4>",
    }

Skip codes (leaky-safe whitelist — ONLY these three surface on the wire):
    * ``not_found_or_cross_tenant`` — collapses 404 + cross-tenant +
      internal audit/delete infra failures into one ambiguous code.
    * ``converted_lock`` — Closed-Won lead OR one with a linked
      customer/job/quote.  Preserved from the LD1 guardrail.
    * ``open_tasks_lock`` — lead with a non-empty
      ``open_task_ids``.  Preserved from the LD1 guardrail.

HTTP:
    * 422 ``{"code": "empty_ids"}``       on ``lead_ids == []``.
    * 422 ``{"code": "bulk_cap_exceeded"}`` on ``len > 100``.
    * 200 with the envelope above on every other outcome.

Guardrail order per id inside ``_hard_delete_lead``:
    tenant/not-found → converted_lock → open_tasks_lock →
    ``write_deletion_audit_entry(resource_type="lead", ...,
    bulk_op_id=<per-call>)`` → ``db.leads.delete_one``.

Every successful delete pairs 1:1 with a ``deletion_audit`` row
stamped with the SAME ``bulk_op_id`` — the batch is queryable as a
group.  The single-row ``DELETE /api/leads/{lid}`` was also
retrofitted to write ``deletion_audit`` (``bulk_op_id=None``).
"""
from __future__ import annotations

import os
import uuid

import pytest

from tests._phase34_http_shim import http
from tests._phase34_asyncio import batch_safe_run as _run

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = http.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def db():
    from config import db as _db
    return _db


@pytest.fixture(scope="module")
def tid(db):
    async def _go():
        t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
        return t["id"]
    return _run(_go())


def _plant_lead(db, tid, **overrides):
    """Insert a fresh lead row + return its id."""
    lid = uuid.uuid4().hex
    doc = {"id": lid, "tenant_id": tid, "name": f"P6-{lid[:6]}",
             "email": f"{lid[:6]}@t.local", "phone": "+15551234567",
             "status": "new", "source": "admin_manual",
             "created_at": "2026-02-15T00:00:00Z"}
    doc.update(overrides)
    _run(db.leads.insert_one(doc))
    return lid


# ═══════════════════════════════════════════════════════════════════════
# Role gate — unchanged from LD1.
# ═══════════════════════════════════════════════════════════════════════
def test_bulk_hard_delete_rejects_customer(customer_headers):
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=customer_headers,
                  json={"lead_ids": ["nope"]}, timeout=30)
    assert r.status_code in (401, 403)


def test_bulk_hard_delete_rejects_unauthenticated():
    r = http.post(f"{API}/leads/bulk-hard-delete",
                  headers={"Content-Type": "application/json"},
                  json={"lead_ids": ["nope"]}, timeout=30)
    assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════
# Payload validation — P6 shape (HTTP 422 w/ ``code`` field).
# ═══════════════════════════════════════════════════════════════════════
def test_bulk_hard_delete_empty_ids_returns_422_empty_ids(super_headers):
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": []}, timeout=30)
    assert r.status_code == 422, r.text
    body = r.json()
    # FastAPI wraps HTTPException detail under "detail".
    assert body["detail"]["code"] == "empty_ids"


def test_bulk_hard_delete_over_100_returns_422_bulk_cap_exceeded(super_headers):
    payload = [uuid.uuid4().hex for _ in range(101)]
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": payload}, timeout=30)
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["detail"]["code"] == "bulk_cap_exceeded"
    assert body["detail"]["cap"] == 100
    assert body["detail"]["attempted"] == 101


def test_bulk_hard_delete_exactly_100_is_accepted(super_headers):
    """Cap is INCLUSIVE at 100 — exactly-100 must not 422."""
    payload = [uuid.uuid4().hex for _ in range(100)]  # all missing
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": payload}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requested"] == 100
    assert body["deleted"] == 0
    # Every one is skipped with the ambiguous code.
    assert len(body["skipped"]) == 100
    assert all(s["code"] == "not_found_or_cross_tenant"
                for s in body["skipped"])


# ═══════════════════════════════════════════════════════════════════════
# Happy path — rows are removed + ``deletion_audit`` rows written,
# each carrying the SAME ``bulk_op_id`` the response returns.
# ═══════════════════════════════════════════════════════════════════════
def test_bulk_hard_delete_happy_path_pairs_with_deletion_audit(
    db, super_headers, tid,
):
    a = _plant_lead(db, tid)
    b = _plant_lead(db, tid)
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": [a, b]}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requested"] == 2
    assert body["deleted"] == 2
    assert body["skipped"] == []
    bulk_op_id = body["bulk_op_id"]
    assert isinstance(bulk_op_id, str) and len(bulk_op_id) >= 32

    # Rows are gone from the collection (real hard delete).
    for lid in (a, b):
        row = _run(db.leads.find_one({"id": lid}))
        assert row is None, f"lead {lid} was not deleted"

    # Every delete pairs 1:1 with a ``deletion_audit`` row on the
    # SAME ``bulk_op_id``.  Order-agnostic set comparison.
    audit_rows = _run(db.deletion_audit.find(
        {"bulk_op_id": bulk_op_id, "resource_type": "lead"},
        {"_id": 0},
    ).to_list(100))
    audited_ids = {r["resource_id"] for r in audit_rows}
    assert audited_ids == {a, b}, (
        f"expected {{a, b}} audited, got {audited_ids}"
    )
    # Full snapshot is stamped on each audit row.
    for row in audit_rows:
        assert row["tenant_id"] == tid
        assert row["action"] == "delete"
        assert row["snapshot"].get("id") in {a, b}
        assert row["snapshot"].get("tenant_id") == tid


# ═══════════════════════════════════════════════════════════════════════
# Safety-lock surfaces — converted_lock, open_tasks_lock.
# ═══════════════════════════════════════════════════════════════════════
def test_bulk_hard_delete_closed_won_surfaces_converted_lock(
    db, super_headers, tid,
):
    """Closed-Won leads with linked jobs / customers surface in
    ``skipped[]`` with ``code=converted_lock``.  No delete.  No
    audit row."""
    a = _plant_lead(db, tid,
                    converted_customer_id=uuid.uuid4().hex,
                    status="closed_won")
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": [a]}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == 0
    assert body["skipped"] == [
        {"lead_id": a, "code": "converted_lock"},
    ]
    # Lead survives.
    assert _run(db.leads.find_one({"id": a})) is not None
    # No audit row written for the skipped lead.
    audit = _run(db.deletion_audit.find_one(
        {"bulk_op_id": body["bulk_op_id"], "resource_id": a}))
    assert audit is None
    # Cleanup.
    _run(db.leads.delete_one({"id": a}))


def test_bulk_hard_delete_open_tasks_surfaces_open_tasks_lock(
    db, super_headers, tid,
):
    a = _plant_lead(db, tid, open_task_ids=["task-1", "task-2"])
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": [a]}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == 0
    assert body["skipped"] == [
        {"lead_id": a, "code": "open_tasks_lock"},
    ]
    assert _run(db.leads.find_one({"id": a})) is not None
    # Cleanup.
    _run(db.leads.delete_one({"id": a}))


# ═══════════════════════════════════════════════════════════════════════
# Cross-tenant + not-found — SAME ambiguous code so the response
# cannot be used to enumerate cross-tenant existence.
# ═══════════════════════════════════════════════════════════════════════
def test_bulk_hard_delete_not_found_id_returns_not_found_or_cross_tenant(
    super_headers,
):
    missing = uuid.uuid4().hex
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": [missing]}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == 0
    assert body["skipped"] == [
        {"lead_id": missing, "code": "not_found_or_cross_tenant"},
    ]


def test_bulk_hard_delete_cross_tenant_returns_not_found_or_cross_tenant(
    db, super_headers,
):
    """A lead that exists in ANOTHER tenant must land in ``skipped``
    with the exact same code the "just not found" case returns.
    Same code prevents cross-tenant existence enumeration."""
    other_tid = "tenant-foreign-" + uuid.uuid4().hex[:6]
    foreign = uuid.uuid4().hex
    _run(db.leads.insert_one({
        "id": foreign, "tenant_id": other_tid, "name": "foreign",
        "status": "new", "created_at": "2026-02-15T00:00:00Z",
    }))
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": [foreign]}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == 0
    assert body["skipped"] == [
        {"lead_id": foreign, "code": "not_found_or_cross_tenant"},
    ]
    # Foreign row untouched.
    survivor = _run(db.leads.find_one({"id": foreign}))
    assert survivor is not None
    # No audit row written on any tenant's collection.
    audit_any = _run(db.deletion_audit.find_one(
        {"resource_id": foreign, "resource_type": "lead"}))
    assert audit_any is None
    # Cleanup so this row doesn't linger across suite runs.
    _run(db.leads.delete_one({"id": foreign}))


# ═══════════════════════════════════════════════════════════════════════
# Idempotency — second call on the same ids after a successful
# delete returns every one in ``skipped`` with the ambiguous code.
# ═══════════════════════════════════════════════════════════════════════
def test_bulk_hard_delete_second_call_on_same_ids_is_all_skipped(
    db, super_headers, tid,
):
    a = _plant_lead(db, tid)
    b = _plant_lead(db, tid)

    # First call — deletes both.
    r1 = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                   json={"lead_ids": [a, b]}, timeout=30)
    assert r1.status_code == 200
    assert r1.json()["deleted"] == 2

    # Second call — same ids — all skipped with the ambiguous code.
    r2 = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                   json={"lead_ids": [a, b]}, timeout=30)
    assert r2.status_code == 200
    body = r2.json()
    assert body["deleted"] == 0
    assert body["requested"] == 2
    codes = sorted(s["code"] for s in body["skipped"])
    assert codes == [
        "not_found_or_cross_tenant",
        "not_found_or_cross_tenant",
    ]
    # Second-call bulk_op_id is DISTINCT from the first.
    assert r2.json()["bulk_op_id"] != r1.json()["bulk_op_id"]


# ═══════════════════════════════════════════════════════════════════════
# Admin role — parity w/ super_admin.  Both pass ``require_admin``.
# ═══════════════════════════════════════════════════════════════════════
def test_bulk_hard_delete_admin_role_allowed(db, admin_headers, tid):
    a = _plant_lead(db, tid)
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=admin_headers,
                  json={"lead_ids": [a]}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == 1
    assert body["skipped"] == []
    assert _run(db.leads.find_one({"id": a})) is None
    # Audit row present with the returned bulk_op_id.
    audit = _run(db.deletion_audit.find_one(
        {"bulk_op_id": body["bulk_op_id"], "resource_id": a},
        {"_id": 0},
    ))
    assert audit is not None
    assert audit["resource_type"] == "lead"


# ═══════════════════════════════════════════════════════════════════════
# Phase P6 · single-row DELETE /api/leads/{lid} retrofit.
# Writes a ``deletion_audit`` row with ``bulk_op_id=None`` — parity
# with the bulk endpoint's audit trail.
# ═══════════════════════════════════════════════════════════════════════
def test_single_row_delete_writes_deletion_audit_with_null_bulk_op_id(
    db, admin_headers, tid,
):
    a = _plant_lead(db, tid)
    r = http.delete(f"{API}/leads/{a}", headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["deleted"] == 1

    # Lead row is gone.
    assert _run(db.leads.find_one({"id": a})) is None

    # ``deletion_audit`` row present with ``bulk_op_id=None`` +
    # ``resource_type="lead"``.
    audit = _run(db.deletion_audit.find_one(
        {"resource_type": "lead", "resource_id": a, "tenant_id": tid},
        {"_id": 0},
    ))
    assert audit is not None, "single-row delete did not audit"
    assert audit["bulk_op_id"] is None
    assert audit["action"] == "delete"
    assert audit["snapshot"].get("id") == a


# ═══════════════════════════════════════════════════════════════════════
# Phase P6 · super-admin deletion-audit viewer retrieves ``lead``.
# Confirms the ``list_deletions`` filter allowlist was extended.
# ═══════════════════════════════════════════════════════════════════════
def test_super_admin_deletion_audit_viewer_returns_lead_rows(
    db, super_headers, tid,
):
    a = _plant_lead(db, tid)
    bulk_r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                       json={"lead_ids": [a]}, timeout=30)
    assert bulk_r.status_code == 200
    bulk_op_id = bulk_r.json()["bulk_op_id"]

    # Retrieve via the super-admin deletion viewer, filtered to
    # ``resource_type=lead``.
    r = http.get(f"{API}/admin/audit/deletions?resource_type=lead&limit=200",
                  headers=super_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["rows"]
    # The just-audited row shows up in the results.
    hits = [
        row for row in rows
        if row.get("resource_id") == a and row.get("bulk_op_id") == bulk_op_id
    ]
    assert len(hits) == 1, (
        f"lead audit row not surfaced through the viewer — "
        f"found={len(hits)} bulk_op_id={bulk_op_id!r}"
    )
    assert hits[0]["resource_type"] == "lead"
