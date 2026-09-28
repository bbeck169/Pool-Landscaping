"""HARD-DELETE · HD-B · Feb-2026 — preview-cascade endpoint tests.

Verifies the read-only cascade preview:

  * Customer preview surfaces correct child counts (jobs, quotes,
    service_reports, files) and photos embedded on service_reports.
  * Preview does NOT persist any state — ``deleted_at`` and every
    stamp is unchanged after the call.
  * External refs surfaced in the payload; ``would_block_purge``
    flag reflects presence.
  * Admin + super_admin both allowed; technician role gets 403.
"""
from __future__ import annotations

import asyncio
import copy
import re
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException


# ─── Reuse the in-memory Motor stub from test_hard_delete_hd_a ──────
# We import the module by path so we share one battle-tested stub
# implementation across HD-A + HD-B tests.
from backend.tests.test_hard_delete_hd_a import (             # noqa: E402
    _DB, _run,
)


@pytest.fixture
def fake_db(monkeypatch):
    fake = _DB()
    fake.customers.rows = [
        {"id": "cust-1", "tenant_id": "t1", "name": "Preview Customer"},
    ]
    fake.jobs.rows = [
        {"id": "job-a", "tenant_id": "t1", "customer_id": "cust-1"},
        {"id": "job-b", "tenant_id": "t1", "customer_id": "cust-1"},
        {"id": "job-c", "tenant_id": "t1", "customer_id": "cust-1"},
    ]
    fake.quotes.rows = [
        {"id": "q-1", "tenant_id": "t1", "customer_id": "cust-1",
         "doc_type": "estimate"},
        {"id": "inv-1", "tenant_id": "t1", "customer_id": "cust-1",
         "doc_type": "invoice"},
        # Two invoices with Stripe payment_intent_id → external ref.
        {"id": "inv-2", "tenant_id": "t1", "customer_id": "cust-1",
         "doc_type": "invoice", "payment_intent_id": "pi_ext_1"},
    ]
    fake.service_reports.rows = [
        {"id": "sr-1", "tenant_id": "t1", "customer_id": "cust-1",
         "job_id": "job-a",
         "photos": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]},
        {"id": "sr-2", "tenant_id": "t1", "customer_id": "cust-1",
         "job_id": "job-b", "photos": []},
    ]
    fake.files.rows = [
        {"id": "f-1", "tenant_id": "t1", "customer_id": "cust-1",
         "filename": "quote.pdf", "is_deleted": False},
        {"id": "f-2", "tenant_id": "t1", "customer_id": "cust-1",
         "filename": "signed.pdf", "is_deleted": False},
    ]
    fake.hard_delete_tombstones.rows = []
    fake.audit_logs.rows = []
    fake.communication_sends.rows = []
    fake.outbound_emails.rows = []

    import importlib
    for mod_name in [
        "services.hard_delete.preview",
        "services.hard_delete.cascade",
        "services.hard_delete.tombstone",
        "routers.hard_delete",
    ]:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "db", fake, raising=False)
    return fake


def test_preview_returns_child_counts(fake_db):
    from services.hard_delete import preview

    res = _run(preview.preview_cascade("customer", "cust-1", "t1"))
    assert res["entity_type"] == "customer"
    assert res["already_soft_deleted"] is False
    counts = res["child_counts"]
    assert counts["jobs"] == 3
    assert counts["quotes"] == 3
    assert counts["service_reports"] == 2
    assert counts["files"] == 2
    # Embedded photos surface as a top-level count.
    assert counts["photos"] == 3


def test_preview_does_not_persist_any_state(fake_db):
    from services.hard_delete import preview

    # Snapshot the DB pre-call.
    before = {
        "customers": copy.deepcopy(fake_db.customers.rows),
        "jobs": copy.deepcopy(fake_db.jobs.rows),
        "quotes": copy.deepcopy(fake_db.quotes.rows),
        "service_reports": copy.deepcopy(fake_db.service_reports.rows),
        "files": copy.deepcopy(fake_db.files.rows),
    }
    _run(preview.preview_cascade("customer", "cust-1", "t1"))
    for coll, rows in before.items():
        assert fake_db[coll].rows == rows, (
            f"preview mutated {coll!r} — payload changed"
        )


def test_preview_surfaces_external_refs(fake_db):
    from services.hard_delete import preview

    res = _run(preview.preview_cascade("customer", "cust-1", "t1"))
    refs = res["external_refs"]
    assert len(refs) == 1
    assert refs[0]["payment_intent_id"] == "pi_ext_1"
    assert res["would_block_purge"] is True


def test_preview_not_found(fake_db):
    from services.hard_delete import preview

    res = _run(preview.preview_cascade("customer", "does-not-exist", "t1"))
    assert res["error_code"] == "not_found"


def test_preview_unsupported_entity_type(fake_db):
    from services.hard_delete import preview

    res = _run(preview.preview_cascade("banana", "whatever", "t1"))
    assert res["error_code"] == "unsupported_entity_type"


def test_preview_endpoint_admin_role_ok(fake_db):
    from routers import hard_delete as router

    res = _run(router.preview_cascade_endpoint(
        entity_type="customer", doc_id="cust-1",
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    assert res["ok"] is True
    assert "child_counts" in res


def test_preview_endpoint_super_admin_role_ok(fake_db):
    from routers import hard_delete as router

    res = _run(router.preview_cascade_endpoint(
        entity_type="customer", doc_id="cust-1",
        user={"id": "u", "role": "super_admin", "email": "s@x"},
        tenant={"id": "t1"},
    ))
    assert res["ok"] is True


def test_preview_endpoint_technician_blocked(fake_db):
    from routers import hard_delete as router

    with pytest.raises(HTTPException) as exc:
        _run(router.preview_cascade_endpoint(
            entity_type="customer", doc_id="cust-1",
            user={"id": "u", "role": "technician", "email": "t@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403


def test_preview_endpoint_manager_blocked(fake_db):
    from routers import hard_delete as router

    with pytest.raises(HTTPException) as exc:
        _run(router.preview_cascade_endpoint(
            entity_type="customer", doc_id="cust-1",
            user={"id": "u", "role": "manager", "email": "m@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403


def test_preview_endpoint_not_found_returns_404(fake_db):
    from routers import hard_delete as router

    with pytest.raises(HTTPException) as exc:
        _run(router.preview_cascade_endpoint(
            entity_type="customer", doc_id="nope",
            user={"id": "u", "role": "admin", "email": "a@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 404
    assert exc.value.detail["error_code"] == "not_found"


def test_preview_reflects_already_soft_deleted(fake_db):
    """Once soft-deleted, preview reflects that state — new child
    counts shouldn't include already-trashed descendants."""
    from services.hard_delete import cascade, preview

    _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u",
    ))
    res = _run(preview.preview_cascade("customer", "cust-1", "t1"))
    assert res["already_soft_deleted"] is True
    # Every child got the same cascade batch — subsequent preview
    # sees them as already-deleted (excluded from a fresh /soft
    # sweep).  Only the embedded photos on already-soft SR rows
    # still count because photos live in the parent doc's array —
    # the preview counts them defensively.
    counts = res["child_counts"]
    assert counts.get("jobs", 0) == 0
    assert counts.get("quotes", 0) == 0
    assert counts.get("service_reports", 0) == 0


def test_preview_job_returns_child_reports_only(fake_db):
    from services.hard_delete import preview

    res = _run(preview.preview_cascade("job", "job-a", "t1"))
    counts = res["child_counts"]
    assert counts["service_reports"] == 1
    # Photos on the SR should also bubble up.
    assert counts["photos"] == 3
    # No jobs / quotes at this level.
    assert "jobs" not in counts
    assert "quotes" not in counts


def test_preview_tenant_scoped(fake_db):
    """A tenant-A caller must NOT see a tenant-B row."""
    from services.hard_delete import preview

    fake_db.customers.rows.append({
        "id": "cross", "tenant_id": "t2", "name": "Other Tenant",
    })
    res = _run(preview.preview_cascade("customer", "cross", "t1"))
    assert res["error_code"] == "not_found"
