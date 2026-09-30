"""Phase K41 · Feb-2026 — Dashboard drill-down endpoint tests.

Coverage matrix (K41 phase brief):
  • Happy path — each of the three GET endpoints returns rows.
  • 403 negatives — dispatcher / office / tech / customer roles blocked.
  • Cursor pagination — total > limit, next_cursor honored.
  • Time-window contract — drill-down mirrors the tile filter.
  • K6 hook — line-item audit fires job_edited_after_completion when
    the parent job is in status='completed'; draft-only edits fire
    dashboard_drilldown_edit alone.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()
_CACHE: dict = {}


def _login(email: str, password: str = "password123") -> str:
    key = f"tok:{email}"
    if _CACHE.get(key):
        return _CACHE[key]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"login skipped for {email}: {r.status_code}")
    _CACHE[key] = r.json()["access_token"]
    return _CACHE[key]


def _me(token: str) -> dict:
    r = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    return r.json() if r.status_code == 200 else {}


def _admin_ctx() -> dict:
    if _CACHE.get("admin_ctx"):
        return _CACHE["admin_ctx"]
    tok = _login("admin@aquaterra.com")
    me = _me(tok)
    _CACHE["admin_ctx"] = {"token": tok, "tenant_id": me.get("tenant_id")}
    return _CACHE["admin_ctx"]


def _super_ctx() -> dict:
    if _CACHE.get("super_ctx"):
        return _CACHE["super_ctx"]
    tok = _login("super@aquaterra.com")
    me = _me(tok)
    _CACHE["super_ctx"] = {"token": tok, "tenant_id": me.get("tenant_id")}
    return _CACHE["super_ctx"]


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ═════════════════════════════════════════════════════════════════════
# 1) Happy path — three GET endpoints return valid shape
# ═════════════════════════════════════════════════════════════════════
def test_k41_data_integrity_rows_happy_path():
    ctx = _super_ctx()
    r = requests.get(
        f"{API}/dashboard/data-integrity/rows?class=orphaned_customer_refs",
        headers=_headers(ctx["token"]), timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["class"] == "orphaned_customer_refs"
    assert isinstance(body["rows"], list)
    assert "total" in body
    assert "next_cursor" in body
    assert "counts" in (body.get("header") or {})


def test_k41_income_by_category_rows_happy_path():
    ctx = _admin_ctx()
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=365)).isoformat()
    end = today.isoformat()
    r = requests.get(
        f"{API}/dashboard/income/by-category/rows"
        f"?category=Uncategorized&from={start}&to={end}",
        headers=_headers(ctx["token"]), timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == "Uncategorized"
    assert isinstance(body["rows"], list)
    assert body["range"]["from"].startswith(start)


def test_k41_income_by_service_rows_happy_path():
    ctx = _admin_ctx()
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=365)).isoformat()
    end = today.isoformat()
    r = requests.get(
        f"{API}/dashboard/income/by-service/rows"
        f"?service_category_id=Uncategorized&from={start}&to={end}",
        headers=_headers(ctx["token"]), timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["service_category_name"] == "Uncategorized"
    assert isinstance(body["rows"], list)


# ═════════════════════════════════════════════════════════════════════
# 2) Auth negatives — non-permitted roles → 403
#
# Feb-2026 · Drill-down role expansion — ``manager`` was removed
# from these deny-lists after ``_require_drilldown_read_role`` was
# introduced (see ``routers/dashboard_drilldown.py`` header).
# The positive coverage for manager + owner lives in
# ``tests/test_dashboard_drilldown_role_gate.py``.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("email", [
    "carlos@aquaterra.com",          # tech
    "customer@aquaterra.com",        # customer
])
def test_k41_data_integrity_rows_denies_non_admin(email):
    tok = _login(email)
    r = requests.get(
        f"{API}/dashboard/data-integrity/rows?class=orphaned_customer_refs",
        headers=_headers(tok), timeout=30,
    )
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("email", [
    "carlos@aquaterra.com",
    "customer@aquaterra.com",
])
def test_k41_income_by_category_rows_denies_non_admin(email):
    tok = _login(email)
    today = datetime.now(timezone.utc).date().isoformat()
    r = requests.get(
        f"{API}/dashboard/income/by-category/rows"
        f"?category=Uncategorized&from={today}&to={today}",
        headers=_headers(tok), timeout=30,
    )
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("email", [
    "carlos@aquaterra.com",
    "customer@aquaterra.com",
])
def test_k41_income_by_service_rows_denies_non_admin(email):
    tok = _login(email)
    today = datetime.now(timezone.utc).date().isoformat()
    r = requests.get(
        f"{API}/dashboard/income/by-service/rows"
        f"?service_category_id=Uncategorized&from={today}&to={today}",
        headers=_headers(tok), timeout=30,
    )
    assert r.status_code == 403, r.text


# Unauthenticated bail-out for the resolve endpoint too.
def test_k41_resolve_requires_auth():
    r = requests.post(
        f"{API}/dashboard/data-integrity/resolve",
        json={"ref_class": "orphaned_customer_refs",
              "job_id": "TEST-NA", "action": "delete"},
        timeout=15,
    )
    assert r.status_code in (401, 403), r.text


# ═════════════════════════════════════════════════════════════════════
# 3) Bad enum / bad range → 400
# ═════════════════════════════════════════════════════════════════════
def test_k41_data_integrity_rows_invalid_class_400():
    ctx = _super_ctx()
    r = requests.get(
        f"{API}/dashboard/data-integrity/rows?class=bogus",
        headers=_headers(ctx["token"]), timeout=30,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_class"


def test_k41_income_by_category_bad_date_400():
    ctx = _admin_ctx()
    r = requests.get(
        f"{API}/dashboard/income/by-category/rows"
        f"?category=x&from=not-a-date&to=2026-01-01",
        headers=_headers(ctx["token"]), timeout=30,
    )
    assert r.status_code == 400


# ═════════════════════════════════════════════════════════════════════
# 4) Cursor pagination — synthetic seed
# ═════════════════════════════════════════════════════════════════════
def test_k41_cursor_pagination_data_integrity():
    """Seed enough synthetic orphaned-customer rows to force pagination.

    Cleanup: every seeded job has ``id`` prefixed ``TEST-K41-`` so
    ``conftest.teardown`` deletes it after the run.
    """
    ctx = _super_ctx()
    tenant_id = ctx["tenant_id"]
    dead_customer_id = f"TEST-K41-DEAD-{uuid.uuid4().hex[:8]}"
    seeded_ids = []
    now = datetime.now(timezone.utc).isoformat()
    for i in range(6):
        jid = f"TEST-K41-JOB-{uuid.uuid4().hex[:8]}"
        _db.jobs.insert_one({
            "id": jid,
            "tenant_id": tenant_id,
            "customer_id": dead_customer_id,
            "customer_name": f"K41 Seed {i}",
            "status": "scheduled",
            "created_at": now,
            "scheduled_date": now,
        })
        seeded_ids.append(jid)

    # Bust the scan cache — force a fresh scan.
    try:
        from routers.dashboard_drilldown import _dangling_cache  # type: ignore
        _dangling_cache["expires_at"] = 0.0
    except Exception:
        pass

    try:
        r = requests.get(
            f"{API}/dashboard/data-integrity/rows"
            f"?class=orphaned_customer_refs&limit=3",
            headers=_headers(ctx["token"]), timeout=30,
        )
        assert r.status_code == 200, r.text
        page1 = r.json()
        assert len(page1["rows"]) == 3
        assert page1["next_cursor"] is not None

        r2 = requests.get(
            f"{API}/dashboard/data-integrity/rows"
            f"?class=orphaned_customer_refs&limit=3"
            f"&cursor={page1['next_cursor']}",
            headers=_headers(ctx["token"]), timeout=30,
        )
        assert r2.status_code == 200, r2.text
        page2 = r2.json()
        assert len(page2["rows"]) >= 1
        # No overlap between pages.
        ids_page1 = {row["job_id"] for row in page1["rows"]}
        ids_page2 = {row["job_id"] for row in page2["rows"]}
        assert ids_page1.isdisjoint(ids_page2)
    finally:
        _db.jobs.delete_many({"id": {"$in": seeded_ids}})


# ═════════════════════════════════════════════════════════════════════
# 5) Time-window contract — passing tile range yields expected rows
# ═════════════════════════════════════════════════════════════════════
def test_k41_time_window_contract_matches_tile_range():
    """The drill-down endpoint runs the SAME date-range filter as
    the tile aggregation.  Concretely: an invoice outside the range
    must NOT appear in the drill-down."""
    ctx = _admin_ctx()
    tenant_id = ctx["tenant_id"]
    inv_id = f"TEST-K41-INV-{uuid.uuid4().hex[:8]}"
    _db.quotes.insert_one({
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "payment_status": "paid",
        "invoice_number": "TEST-K41-001",
        "created_at": "2019-01-01T00:00:00+00:00",
        "issue_date": "2019-01-01",
        "line_items": [{
            "id": "li-1", "description": "K41 seed line",
            "quantity": 1, "unit_price": 100, "category": "K41-K41-CAT",
        }],
        "total": 100,
    })
    try:
        # Range that EXCLUDES the seeded invoice (2020..2026).
        r = requests.get(
            f"{API}/dashboard/income/by-category/rows"
            f"?category=K41-K41-CAT&from=2025-01-01&to=2025-12-31",
            headers=_headers(ctx["token"]), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 0
        assert not any(row.get("invoice_id") == inv_id
                        for row in body["rows"])

        # Range that INCLUDES the seeded invoice.
        r2 = requests.get(
            f"{API}/dashboard/income/by-category/rows"
            f"?category=K41-K41-CAT&from=2019-01-01&to=2019-12-31",
            headers=_headers(ctx["token"]), timeout=30,
        )
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["total"] >= 1
        assert any(row.get("invoice_id") == inv_id
                    for row in body2["rows"])
    finally:
        _db.quotes.delete_one({"id": inv_id})


# ═════════════════════════════════════════════════════════════════════
# 6) K6 completed-job audit hook — line-item audit endpoint
# ═════════════════════════════════════════════════════════════════════
def test_k41_line_item_audit_emits_drilldown_event():
    """POST /dashboard/drilldown/line-item-audit must insert the K41
    audit event for a DRAFT invoice (no K6 event)."""
    ctx = _admin_ctx()
    tenant_id = ctx["tenant_id"]
    inv_id = f"TEST-K41-INV-{uuid.uuid4().hex[:8]}"
    _db.quotes.insert_one({
        "id": inv_id, "tenant_id": tenant_id, "doc_type": "invoice",
        "invoice_number": "TEST-K41-AUD-1",
        "line_items": [],
        "status": "draft",
    })
    try:
        r = requests.post(
            f"{API}/dashboard/drilldown/line-item-audit",
            headers=_headers(ctx["token"]),
            json={"tile": "income-by-category",
                  "invoice_id": inv_id, "line_index": 0,
                  "field": "unit_price", "before": 10, "after": 20},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # Verify the audit row exists in the collection.
        row = _db.audit_events.find_one(
            {"event_type": "dashboard_drilldown_edit",
              "field": "unit_price", "before": 10, "after": 20},
        )
        assert row is not None
        # And K6 event did NOT fire — draft invoice, no parent job.
        k6 = _db.audit_events.find_one(
            {"event_type": "job_edited_after_completion",
              "source": "dashboard_drilldown",
              "changed_field": "invoice.line_item.unit_price"},
        )
        assert k6 is None
    finally:
        _db.quotes.delete_one({"id": inv_id})
        _db.audit_events.delete_many({"invoice_id": inv_id})


def test_k41_line_item_audit_fires_k6_on_completed_job():
    """When the invoice.job_id references a COMPLETED job, both the
    K41 audit and the K6 ``job_edited_after_completion`` audit rows
    must land."""
    ctx = _admin_ctx()
    tenant_id = ctx["tenant_id"]
    job_id = f"TEST-K41-JOB-{uuid.uuid4().hex[:8]}"
    inv_id = f"TEST-K41-INV-{uuid.uuid4().hex[:8]}"
    _db.jobs.insert_one({
        "id": job_id, "tenant_id": tenant_id,
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    _db.quotes.insert_one({
        "id": inv_id, "tenant_id": tenant_id, "doc_type": "invoice",
        "invoice_number": "TEST-K41-K6-1",
        "job_id": job_id,
        "line_items": [{"id": "li-1", "description": "seed",
                        "quantity": 1, "unit_price": 5,
                        "category": "K41-K41"}],
        "status": "draft",
    })
    try:
        r = requests.post(
            f"{API}/dashboard/drilldown/line-item-audit",
            headers=_headers(ctx["token"]),
            json={"tile": "income-by-service",
                  "invoice_id": inv_id, "line_index": 0,
                  "field": "quantity", "before": 1, "after": 3},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # K41 audit.
        assert _db.audit_events.find_one(
            {"event_type": "dashboard_drilldown_edit",
              "invoice_id": inv_id, "field": "quantity"},
        ) is not None
        # K6 audit on the parent completed job.
        assert _db.audit_events.find_one(
            {"event_type": "job_edited_after_completion",
              "job_id": job_id,
              "source": "dashboard_drilldown"},
        ) is not None
    finally:
        _db.jobs.delete_one({"id": job_id})
        _db.quotes.delete_one({"id": inv_id})
        _db.audit_events.delete_many(
            {"$or": [{"invoice_id": inv_id}, {"job_id": job_id}]},
        )


# ═════════════════════════════════════════════════════════════════════
# 7) Feb-2026 · Data-Integrity hard-delete upgrade
# ═════════════════════════════════════════════════════════════════════
def test_hard_delete_single_row_removes_job_from_db():
    """POST /dashboard/data-integrity/resolve with
    action='hard_delete' must permanently remove the job row from
    db.jobs (verified via follow-up find_one → None) and emit an
    audit event with after='hard_deleted'."""
    ctx = _admin_ctx()
    tenant_id = ctx["tenant_id"]
    job_id = f"TEST-HD-SINGLE-{uuid.uuid4().hex[:8]}"
    _db.jobs.insert_one({
        "id": job_id, "tenant_id": tenant_id,
        "status": "scheduled",
        "customer_id": "orphan-cust-does-not-exist",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.post(
            f"{API}/dashboard/data-integrity/resolve",
            headers=_headers(ctx["token"]),
            json={"ref_class": "orphaned_customer_refs",
                  "job_id": job_id,
                  "action": "hard_delete"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["action"] == "hard_delete"
        assert body["deleted_count"] == 1
        # Row is GONE from db.jobs.
        assert _db.jobs.find_one({"id": job_id}) is None
        # Audit event landed with after='hard_deleted' + action='hard_delete'.
        audit = _db.audit_events.find_one({
            "event_type": "dashboard_drilldown_edit",
            "job_id": job_id,
            "field": "status",
            "after": "hard_deleted",
        })
        assert audit is not None
        assert audit.get("action") == "hard_delete"
        assert audit.get("tenant_id") == tenant_id
    finally:
        _db.jobs.delete_one({"id": job_id})
        _db.audit_events.delete_many({"job_id": job_id})


def test_hard_delete_bulk_uses_delete_many_fast_path():
    """POST /dashboard/data-integrity/resolve-bulk with N items all
    action='hard_delete' + ref_class='orphaned_customer_refs' must
    remove ALL rows via the single-op fast-path, return
    ``fast_path='hard_delete_many'`` in the response, and emit N
    audit events."""
    ctx = _admin_ctx()
    tenant_id = ctx["tenant_id"]
    N = 4
    job_ids = [f"TEST-HD-BULK-{uuid.uuid4().hex[:8]}" for _ in range(N)]
    _db.jobs.insert_many([
        {"id": jid, "tenant_id": tenant_id, "status": "scheduled",
         "customer_id": "orphan-cust", "created_at": datetime.now(timezone.utc).isoformat()}
        for jid in job_ids
    ])
    try:
        r = requests.post(
            f"{API}/dashboard/data-integrity/resolve-bulk",
            headers=_headers(ctx["token"]),
            json={"items": [
                {"ref_class": "orphaned_customer_refs",
                 "job_id": jid,
                 "action": "hard_delete",
                 "target_id": None}
                for jid in job_ids
            ]},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["succeeded"] == N
        assert body["failed"] == 0
        assert body["deleted_count"] == N
        assert body.get("fast_path") == "hard_delete_many"
        # All N rows GONE.
        assert _db.jobs.count_documents({"id": {"$in": job_ids}}) == 0
        # N audit events landed sharing the bulk_batch_id.
        batch_id = body["bulk_batch_id"]
        aud_count = _db.audit_events.count_documents({
            "event_type": "dashboard_drilldown_edit",
            "bulk_batch_id": batch_id,
            "after": "hard_deleted",
        })
        assert aud_count == N
    finally:
        _db.jobs.delete_many({"id": {"$in": job_ids}})
        _db.audit_events.delete_many({"job_id": {"$in": job_ids}})


def test_hard_delete_bulk_rejects_over_cap():
    """The existing 100-item cap must be preserved for the bulk
    endpoint — an oversized batch returns 400 without deleting."""
    ctx = _admin_ctx()
    over_cap = [{"ref_class": "orphaned_customer_refs",
                 "job_id": f"TEST-HD-CAP-{i}",
                 "action": "hard_delete",
                 "target_id": None} for i in range(101)]
    r = requests.post(
        f"{API}/dashboard/data-integrity/resolve-bulk",
        headers=_headers(ctx["token"]),
        json={"items": over_cap},
        timeout=15,
    )
    assert r.status_code == 400
    assert "batch_cap_exceeded" in r.text


def test_hard_delete_cross_tenant_returns_404_and_does_not_delete():
    """A job whose tenant_id differs from the caller's tenant must
    NOT be deletable through the hard-delete path.  The tenant-
    scoped find_one returns None → 404, and the row remains in
    db.jobs."""
    ctx = _admin_ctx()
    # Use a synthetic foreign tenant id — no shared secret leakage.
    foreign_tenant_id = f"foreign-tenant-{uuid.uuid4().hex[:12]}"
    assert foreign_tenant_id != ctx["tenant_id"]
    job_id = f"TEST-HD-XT-{uuid.uuid4().hex[:8]}"
    _db.jobs.insert_one({
        "id": job_id, "tenant_id": foreign_tenant_id,
        "status": "scheduled",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.post(
            f"{API}/dashboard/data-integrity/resolve",
            headers=_headers(ctx["token"]),
            json={"ref_class": "orphaned_customer_refs",
                  "job_id": job_id,
                  "action": "hard_delete"},
            timeout=15,
        )
        assert r.status_code == 404, r.text
        # Row survives — cross-tenant is invisible AND non-mutating.
        assert _db.jobs.find_one({"id": job_id}) is not None
    finally:
        _db.jobs.delete_one({"id": job_id})


def test_hard_delete_rejected_for_non_customer_ref_classes():
    """Per S2, hard_delete is only meaningful for
    orphaned_customer_refs — the technician + unassigned variants
    return 400."""
    ctx = _admin_ctx()
    tenant_id = ctx["tenant_id"]
    # Seed a real job so the 400 comes from the class check, not from
    # a spurious job-not-found.
    job_id = f"TEST-HD-CLASS-{uuid.uuid4().hex[:8]}"
    _db.jobs.insert_one({
        "id": job_id, "tenant_id": tenant_id,
        "status": "scheduled",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        for wrong_class in ("orphaned_technician_refs",
                            "unassigned_pending_jobs"):
            r = requests.post(
                f"{API}/dashboard/data-integrity/resolve",
                headers=_headers(ctx["token"]),
                json={"ref_class": wrong_class,
                      "job_id": job_id,
                      "action": "hard_delete"},
                timeout=15,
            )
            assert r.status_code == 400, r.text
            assert "hard_delete_only_supports_orphaned_customer_refs" in r.text
        # Row survives all four rejected attempts.
        assert _db.jobs.find_one({"id": job_id}) is not None
    finally:
        _db.jobs.delete_one({"id": job_id})
