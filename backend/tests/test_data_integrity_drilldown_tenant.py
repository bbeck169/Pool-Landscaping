"""Feb-2026 · P0 fix · tenant scoping for the data-integrity
drill-down handler.

Regression coverage for the two bugs behind the "Dangling Refs"
500:

  1. ``dashboard_drilldown.data_integrity_rows`` called
     ``_scan_dangling_refs()`` argument-less — the scanner had
     been made tenant-scoped under Phase R1 and now requires a
     ``tenant_id`` positional.  Every request threw 500.

  2. The 60-second in-memory cache was a single-bucket dict
     (``{"expires_at": ..., "payload": ...}``) — even after the
     scan-call was patched, tenant A's warm cache would satisfy
     tenant B's request within the TTL window, leaking rows
     across tenants.

This suite locks:
  * The handler now requires + threads ``tenant["id"]`` into
    ``_scan_dangling_refs``.
  * The cache is keyed by ``tenant_id``.
  * Cache TTL is preserved per bucket.
  * Cross-tenant cache isolation holds.

Same in-memory Motor stub harness as
``test_data_repair_tenant_scope_r1.py`` — no live MongoDB.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from routers import dashboard_drilldown as dd
from routers import data_repair as dr

from tests.test_data_repair_dry_run import _DB, _run


TENANT_A = "tenant-A-di"
TENANT_B = "tenant-B-di"


# ═══════════════════════════════════════════════════════════════════
# Two-tenant fixture — each with dangling refs across all 3 classes.
# ═══════════════════════════════════════════════════════════════════
def _two_tenant_db(monkeypatch):
    customers = [
        {"id": "cA-live", "tenant_id": TENANT_A},
        {"id": "cB-live", "tenant_id": TENANT_B},
    ]
    techs = [
        {"id": "techA-live", "tenant_id": TENANT_A},
        {"id": "techB-live", "tenant_id": TENANT_B},
    ]
    users: List[Dict[str, Any]] = []
    jobs = [
        # ── Tenant A ─────────────────────────────────────────────
        {"id": "jA-orphan-cust", "tenant_id": TENANT_A,
         "customer_id": "cA-GHOST", "customer_name": "A · Ghost",
         "technician_id": "techA-live", "status": "scheduled",
         "scheduled_date": "2026-08-01"},
        {"id": "jA-orphan-tech", "tenant_id": TENANT_A,
         "customer_id": "cA-live",
         "technician_id": "techA-GHOST", "technician_name": "A · Ghost T",
         "status": "pending", "scheduled_date": "2026-08-02"},
        {"id": "jA-unassigned", "tenant_id": TENANT_A,
         "customer_id": "cA-live",
         "technician_id": None, "crew_id": None,
         "status": "requested", "scheduled_date": "2026-08-03"},
        # ── Tenant B ─────────────────────────────────────────────
        {"id": "jB-orphan-cust", "tenant_id": TENANT_B,
         "customer_id": "cB-GHOST", "customer_name": "B · Ghost",
         "technician_id": "techB-live", "status": "scheduled",
         "scheduled_date": "2026-08-04"},
        {"id": "jB-orphan-tech", "tenant_id": TENANT_B,
         "customer_id": "cB-live",
         "technician_id": "techB-GHOST", "technician_name": "B · Ghost T",
         "status": "pending", "scheduled_date": "2026-08-05"},
        {"id": "jB-unassigned", "tenant_id": TENANT_B,
         "customer_id": "cB-live",
         "technician_id": None, "crew_id": None,
         "status": "requested", "scheduled_date": "2026-08-06"},
    ]
    fake = _DB(jobs=jobs, customers=customers, technicians=techs, users=users)
    monkeypatch.setattr(dr, "db", fake)
    # Reset the module-level drill-down cache so this test can't be
    # poisoned by a previous test in the same process.
    monkeypatch.setattr(dd, "_dangling_cache", {})
    return fake


def _admin(tenant_id: str, uid: str = "admin-uid") -> Dict[str, Any]:
    return {"id": uid, "role": "admin", "tenant_id": tenant_id}


def _tenant(tenant_id: str) -> Dict[str, Any]:
    return {"id": tenant_id, "name": tenant_id}


# ═══════════════════════════════════════════════════════════════════
# 1 · Tenant scope — each tenant sees only its own rows.
# ═══════════════════════════════════════════════════════════════════
def test_data_integrity_rows_tenant_a_only(monkeypatch):
    _two_tenant_db(monkeypatch)
    payload = _run(dd.data_integrity_rows(
        issue_class="orphaned_customer_refs",
        limit=100,
        cursor=None,
        user=_admin(TENANT_A),
        tenant=_tenant(TENANT_A),
    ))
    job_ids = [r["job_id"] for r in payload["rows"]]
    assert "jA-orphan-cust" in job_ids
    assert "jB-orphan-cust" not in job_ids
    assert payload["total"] == 1
    # Header counts also scope to the requester tenant only.
    counts = payload["header"]["counts"]
    assert counts["orphaned_customer_refs"] == 1
    assert counts["orphaned_technician_refs"] == 1
    assert counts["unassigned_pending_jobs"] == 1


def test_data_integrity_rows_tenant_b_only(monkeypatch):
    """Symmetric proof — tenant B sees ONLY tenant B's dangling
    refs.  Rules out a hardcoded-TENANT_A fix."""
    _two_tenant_db(monkeypatch)
    payload = _run(dd.data_integrity_rows(
        issue_class="orphaned_customer_refs",
        limit=100,
        cursor=None,
        user=_admin(TENANT_B),
        tenant=_tenant(TENANT_B),
    ))
    job_ids = [r["job_id"] for r in payload["rows"]]
    assert "jB-orphan-cust" in job_ids
    assert not any(jid.startswith("jA-") for jid in job_ids)


# ═══════════════════════════════════════════════════════════════════
# 2 · Cache TTL — a second call within 60s reuses the bucket.
# ═══════════════════════════════════════════════════════════════════
def test_data_integrity_rows_reuses_cached_scan_within_ttl(monkeypatch):
    """Two consecutive tenant-A calls → the underlying
    ``_scan_dangling_refs`` fires exactly ONCE."""
    _two_tenant_db(monkeypatch)
    # Wrap the real ``_scan_dangling_refs`` with a call-counting
    # AsyncMock that forwards to the original implementation.
    real_scan = dr._scan_dangling_refs
    call_counter = AsyncMock(side_effect=real_scan)
    # ``_cached_scan_dangling`` imported the name at module import
    # time — patch the reference the drill-down module holds.
    monkeypatch.setattr(dd, "_scan_dangling_refs", call_counter)

    _run(dd.data_integrity_rows(
        issue_class="orphaned_customer_refs", limit=100, cursor=None,
        user=_admin(TENANT_A), tenant=_tenant(TENANT_A),
    ))
    _run(dd.data_integrity_rows(
        issue_class="orphaned_technician_refs", limit=100, cursor=None,
        user=_admin(TENANT_A), tenant=_tenant(TENANT_A),
    ))
    assert call_counter.await_count == 1, (
        "expected the second tenant-A call to be served from cache; "
        f"got {call_counter.await_count} scan invocations"
    )


# ═══════════════════════════════════════════════════════════════════
# 3 · Cross-tenant cache isolation.
# ═══════════════════════════════════════════════════════════════════
def test_data_integrity_rows_cache_never_leaks_across_tenants(monkeypatch):
    """Tenant A warms the cache → tenant B's request MUST still
    see only tenant B's rows AND MUST trigger a fresh scan (so
    the tenant_id is threaded, not defaulted from the warm bucket).
    """
    _two_tenant_db(monkeypatch)
    real_scan = dr._scan_dangling_refs
    call_counter = AsyncMock(side_effect=real_scan)
    monkeypatch.setattr(dd, "_scan_dangling_refs", call_counter)

    # Tenant A warms the cache.
    _run(dd.data_integrity_rows(
        issue_class="orphaned_customer_refs", limit=100, cursor=None,
        user=_admin(TENANT_A), tenant=_tenant(TENANT_A),
    ))
    assert call_counter.await_count == 1

    # Tenant B's request — MUST trigger a fresh scan AND return
    # only tenant-B rows.
    payload_b = _run(dd.data_integrity_rows(
        issue_class="orphaned_customer_refs", limit=100, cursor=None,
        user=_admin(TENANT_B), tenant=_tenant(TENANT_B),
    ))
    assert call_counter.await_count == 2  # not served from A's bucket
    job_ids = [r["job_id"] for r in payload_b["rows"]]
    assert "jB-orphan-cust" in job_ids
    assert not any(jid.startswith("jA-") for jid in job_ids)

    # And the cached-A bucket is untouched — a repeat tenant-A
    # call within the TTL is still served from cache (no third
    # scan call).
    _run(dd.data_integrity_rows(
        issue_class="unassigned_pending_jobs", limit=100, cursor=None,
        user=_admin(TENANT_A), tenant=_tenant(TENANT_A),
    ))
    assert call_counter.await_count == 2  # still 2 — A cache is warm


# ═══════════════════════════════════════════════════════════════════
# 4 · Admin gate — non-admins are still rejected.
# ═══════════════════════════════════════════════════════════════════
def test_data_integrity_rows_rejects_non_admin(monkeypatch):
    from fastapi import HTTPException
    _two_tenant_db(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        _run(dd.data_integrity_rows(
            issue_class="orphaned_customer_refs", limit=100, cursor=None,
            user={"id": "u", "role": "technician", "tenant_id": TENANT_A},
            tenant=_tenant(TENANT_A),
        ))
    assert exc.value.status_code == 403
