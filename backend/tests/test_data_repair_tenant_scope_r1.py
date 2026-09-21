"""Phase R1 · Feb-2026 — Data Repair tenant-scope regression suite.

The F2 ``data-repair`` scan + apply was previously global — a
super_admin in tenant A could see (and apply repairs to) tenant
B's data.  Phase R1 locks strict tenant scoping:

* ``_scan_dangling_refs(tenant_id)`` — filters ``customers``,
  ``technicians``, ``users``, and ``jobs`` on ``tenant_id``.
* Dry-run + apply endpoints resolve the requester's ``tenant_id``
  via ``_resolve_requester_tenant`` and thread it through.
* Persisted scan doc stores ``tenant_id``; ``_load_scan``
  rejects any mismatch with 403 ``stale_tenant_scope``.
* Apply-helper ``find_one`` / ``update_one`` pin ``tenant_id`` to
  the REQUESTER's tenant, not the scan row's — defense in depth.
* Response payload for both endpoints echoes ``tenant_id``.

This file is the regression backstop for those guarantees.  Uses
the same in-memory Motor stubs (``_DB`` / ``_run``) as the
pre-R1 suite so we don't need a live MongoDB fixture.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from routers import data_repair as dr

from tests.test_data_repair_dry_run import _DB, _run


TENANT_A = "tenant-A-aa11"
TENANT_B = "tenant-B-bb22"


# ═══════════════════════════════════════════════════════════════════
# Two-tenant fixture — each with dangling refs across all 3 classes.
# ═══════════════════════════════════════════════════════════════════
def _two_tenant_db(monkeypatch):
    """Seed one ``_DB`` that carries orphaned refs for two tenants
    in parallel.  Each tenant has:

    * one orphan-customer job (dangling ``customer_id``),
    * one orphan-tech job (dangling ``technician_id``),
    * one unassigned-pending job (flag only, no repair action).
    """
    customers = [
        # Tenant A — one live customer.
        {"id": "cA-live", "tenant_id": TENANT_A},
        # Tenant B — one live customer.
        {"id": "cB-live", "tenant_id": TENANT_B},
    ]
    techs = [
        {"id": "techA-live", "tenant_id": TENANT_A},
        {"id": "techB-live", "tenant_id": TENANT_B},
    ]
    users: List[Dict[str, Any]] = []
    jobs = [
        # ── Tenant A ────────────────────────────────────────────
        {"id": "jA-orphan-cust", "tenant_id": TENANT_A,
         "customer_id": "cA-GHOST", "customer_name": "A · Ghost",
         "technician_id": "techA-live", "status": "scheduled",
         "scheduled_date": "2026-08-01"},
        {"id": "jA-orphan-tech", "tenant_id": TENANT_A,
         "customer_id": "cA-live",
         "technician_id": "techA-GHOST", "technician_name": "A · Ghost Tech",
         "status": "pending", "scheduled_date": "2026-08-02"},
        {"id": "jA-unassigned", "tenant_id": TENANT_A,
         "customer_id": "cA-live",
         "technician_id": None, "crew_id": None,
         "status": "requested", "scheduled_date": "2026-08-03"},
        # ── Tenant B ────────────────────────────────────────────
        {"id": "jB-orphan-cust", "tenant_id": TENANT_B,
         "customer_id": "cB-GHOST", "customer_name": "B · Ghost",
         "technician_id": "techB-live", "status": "scheduled",
         "scheduled_date": "2026-08-04"},
        {"id": "jB-orphan-tech", "tenant_id": TENANT_B,
         "customer_id": "cB-live",
         "technician_id": "techB-GHOST", "technician_name": "B · Ghost Tech",
         "status": "pending", "scheduled_date": "2026-08-05"},
        {"id": "jB-unassigned", "tenant_id": TENANT_B,
         "customer_id": "cB-live",
         "technician_id": None, "crew_id": None,
         "status": "requested", "scheduled_date": "2026-08-06"},
    ]
    fake = _DB(jobs=jobs, customers=customers, technicians=techs, users=users)
    monkeypatch.setattr(dr, "db", fake)
    # Reset the tenant-keyed cache so this test isn't influenced by
    # leftover state from another test in the same process.
    monkeypatch.setattr(dr, "_dry_run_cache", {})
    return fake


def _sa(tenant_id: str, uid: str = "sa-uid") -> Dict[str, Any]:
    return {"id": uid, "role": "super_admin", "tenant_id": tenant_id}


# ═══════════════════════════════════════════════════════════════════
# 1 · Dry-run scope isolation.
# ═══════════════════════════════════════════════════════════════════
def test_dry_run_returns_only_requester_tenant_refs(monkeypatch):
    """Tenant A's super_admin runs dry-run → response contains
    ONLY tenant A's dangling refs.  Tenant B's rows must be
    entirely absent."""
    fake = _two_tenant_db(monkeypatch)
    payload = _run(dr.data_repair_dry_run(user=_sa(TENANT_A)))

    # ── Payload echoes the tenant we scoped to.
    assert payload["tenant_id"] == TENANT_A

    orphan_cust_ids = [r["job_id"] for r in payload["orphaned_customer_refs"]]
    orphan_tech_ids = [r["job_id"] for r in payload["orphaned_technician_refs"]]
    unassigned_ids = [r["job_id"] for r in payload["unassigned_pending_jobs"]]

    # ── Tenant A rows present.
    assert "jA-orphan-cust" in orphan_cust_ids
    assert "jA-orphan-tech" in orphan_tech_ids
    assert "jA-unassigned" in unassigned_ids

    # ── Tenant B rows MUST be absent.
    assert "jB-orphan-cust" not in orphan_cust_ids
    assert "jB-orphan-tech" not in orphan_tech_ids
    assert "jB-unassigned" not in unassigned_ids

    # ── Counts exactly match tenant A's fixture (1 of each class).
    assert len(orphan_cust_ids) == 1
    assert len(orphan_tech_ids) == 1
    assert len(unassigned_ids) == 1
    assert payload["summary"]["total_would_change"] == 2  # cust + tech
    assert payload["summary"]["total_flagged_no_action"] == 1

    # ── Persisted scan doc carries the tenant_id.
    stored = fake.data_integrity_scans.inserts[0]
    assert stored["tenant_id"] == TENANT_A


def test_dry_run_tenant_b_sees_only_tenant_b(monkeypatch):
    """Symmetric proof — tenant B's super_admin sees only tenant
    B's rows.  Rules out an "accidentally hardcoded TENANT_A" fix."""
    _two_tenant_db(monkeypatch)
    payload = _run(dr.data_repair_dry_run(user=_sa(TENANT_B)))
    assert payload["tenant_id"] == TENANT_B
    for bucket_key, prefix in [
        ("orphaned_customer_refs", "jB-orphan-cust"),
        ("orphaned_technician_refs", "jB-orphan-tech"),
        ("unassigned_pending_jobs", "jB-unassigned"),
    ]:
        job_ids = [r["job_id"] for r in payload[bucket_key]]
        assert prefix in job_ids
        assert not any(jid.startswith("jA-") for jid in job_ids)


# ═══════════════════════════════════════════════════════════════════
# 2 · Apply scope isolation — happy path.
# ═══════════════════════════════════════════════════════════════════
def test_apply_tenant_a_only_mutates_tenant_a(monkeypatch):
    """Tenant A super_admin runs full flow → tenant A dangling
    refs resolved; tenant B jobs pixel-identical to their seed."""
    fake = _two_tenant_db(monkeypatch)
    user_a = _sa(TENANT_A)
    payload = _run(dr.data_repair_dry_run(user=user_a))

    body = dr.ApplyIn(
        confirm_token=payload["confirm_token"],
        dry_run_scan_timestamp=payload["scan_timestamp"],
    )
    result = _run(dr.data_repair_apply(body, user=user_a))

    # Response echoes tenant.
    assert result["tenant_id"] == TENANT_A
    assert result["changes_applied"] == 2  # A's cust + A's tech
    assert result["no_op"] is False

    # Tenant A's orphan-cust job soft-deleted.
    row_ja_cust = next(r for r in fake.jobs.rows if r["id"] == "jA-orphan-cust")
    assert row_ja_cust["status"] == "deleted"
    assert row_ja_cust["deleted_reason"] == "data_repair_orphaned_customer"

    # Tenant A's orphan-tech job nulled.
    row_ja_tech = next(r for r in fake.jobs.rows if r["id"] == "jA-orphan-tech")
    assert row_ja_tech["technician_id"] is None
    assert row_ja_tech["technician_name"] == "A · Ghost Tech"  # denorm preserved

    # ── Tenant B ROWS PIXEL-IDENTICAL to seed — no mutation.
    row_jb_cust = next(r for r in fake.jobs.rows if r["id"] == "jB-orphan-cust")
    assert row_jb_cust.get("status") == "scheduled"
    assert "deleted_at" not in row_jb_cust
    row_jb_tech = next(r for r in fake.jobs.rows if r["id"] == "jB-orphan-tech")
    assert row_jb_tech.get("technician_id") == "techB-GHOST"

    # Every audit row carries tenant A.
    for audit in fake.data_integrity_repairs.inserts:
        assert audit["tenant_id"] == TENANT_A


# ═══════════════════════════════════════════════════════════════════
# 3 · Apply-side defense in depth — hand-crafted cross-tenant row.
# ═══════════════════════════════════════════════════════════════════
def test_apply_ignores_hand_crafted_cross_tenant_scan_row(monkeypatch):
    """Attacker scenario: tenant A super_admin can see (via a
    compromise of the ``data_integrity_scans`` collection or an
    intermediate) how to append arbitrary rows to the scan
    document.  If they append a tenant B row + present the tenant
    A scan token, the apply helpers must refuse to mutate that
    tenant B job — because the ``update_one`` filter pins
    ``tenant_id`` to the REQUESTER (tenant A), not the scan row.
    """
    fake = _two_tenant_db(monkeypatch)
    user_a = _sa(TENANT_A)
    payload = _run(dr.data_repair_dry_run(user=user_a))

    # Locate tenant A's persisted scan and inject a hand-crafted
    # tenant B orphan-tech row.  In prod this would require write
    # access to ``data_integrity_scans`` — we simulate that here.
    scan = next(iter(fake.data_integrity_scans.rows))
    injected = {
        "job_id": "jB-orphan-tech",
        "tenant_id": TENANT_B,
        "technician_id": "techB-GHOST",
        "technician_name_denorm": "B · Ghost Tech",
        "would_action": "null_technician_id",
    }
    scan["classes"]["orphaned_technician_refs"].append(injected)

    body = dr.ApplyIn(
        confirm_token=payload["confirm_token"],
        dry_run_scan_timestamp=payload["scan_timestamp"],
    )
    result = _run(dr.data_repair_apply(body, user=user_a))

    # The legitimate tenant A tech row still applied (1).  The
    # hand-crafted tenant B row must NOT have applied because the
    # ``find_one({"id": jid, "tenant_id": TENANT_A})`` matched 0.
    a_tech_applied = any(
        a["target_id"] == "jA-orphan-tech"
        for a in fake.data_integrity_repairs.inserts
    )
    b_tech_applied = any(
        a["target_id"] == "jB-orphan-tech"
        for a in fake.data_integrity_repairs.inserts
    )
    assert a_tech_applied is True
    assert b_tech_applied is False

    # ── Tenant B's job is pixel-identical to its seed.
    row_jb_tech = next(r for r in fake.jobs.rows if r["id"] == "jB-orphan-tech")
    assert row_jb_tech.get("technician_id") == "techB-GHOST"
    assert row_jb_tech.get("technician_name") == "B · Ghost Tech"


# ═══════════════════════════════════════════════════════════════════
# 4 · Cross-tenant scan_token replay — 403 stale_tenant_scope.
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_scan_token_replay_403(monkeypatch):
    """Tenant A mints a scan.  Tenant B super_admin (with valid
    JWT for tenant B) tries to apply that scan_token.
    ``_load_scan`` must reject with 403 ``stale_tenant_scope``."""
    _two_tenant_db(monkeypatch)
    user_a = _sa(TENANT_A, uid="sa-A")
    user_b = _sa(TENANT_B, uid="sa-B")

    a_payload = _run(dr.data_repair_dry_run(user=user_a))
    body = dr.ApplyIn(
        confirm_token=a_payload["confirm_token"],
        dry_run_scan_timestamp=a_payload["scan_timestamp"],
    )
    with pytest.raises(HTTPException) as exc:
        _run(dr.data_repair_apply(body, user=user_b))
    assert exc.value.status_code == 403
    assert "stale_tenant_scope" in str(exc.value.detail).lower()


def test_load_scan_directly_rejects_wrong_tenant(monkeypatch):
    """The ``_load_scan`` helper is exercised directly with a
    tenant mismatch — same 403 stale_tenant_scope must fire."""
    fake = _two_tenant_db(monkeypatch)
    _run(dr.data_repair_dry_run(user=_sa(TENANT_A)))
    stored = fake.data_integrity_scans.inserts[0]

    with pytest.raises(HTTPException) as exc:
        _run(dr._load_scan(
            stored["confirm_token"], stored["scan_timestamp"], TENANT_B,
        ))
    assert exc.value.status_code == 403
    assert "stale_tenant_scope" in str(exc.value.detail).lower()


# ═══════════════════════════════════════════════════════════════════
# 5 · Pre-R1 scan docs (no tenant_id) still rejected.
# ═══════════════════════════════════════════════════════════════════
def test_load_scan_rejects_pre_r1_scan_docs(monkeypatch):
    """A scan doc written before R1 (no ``tenant_id`` field) must
    be rejected as ``stale_tenant_scope`` — we do NOT default to
    the requester's tenant, that would resurrect the bug."""
    fake = _DB(jobs=[], customers=[])
    monkeypatch.setattr(dr, "db", fake)
    pre_r1_scan = {
        "confirm_token": "pre-r1-token",
        "scan_timestamp": "2026-01-01T00:00:00Z",
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=14),
        "actor_user_id": "sa-1",
        "classes": {"orphaned_customer_refs": [],
                    "orphaned_technician_refs": [],
                    "unassigned_pending_jobs": []},
        # NO tenant_id field.
    }
    _run(fake.data_integrity_scans.insert_one(pre_r1_scan))

    with pytest.raises(HTTPException) as exc:
        _run(dr._load_scan("pre-r1-token", "2026-01-01T00:00:00Z", TENANT_A))
    assert exc.value.status_code == 403
    assert "stale_tenant_scope" in str(exc.value.detail).lower()


# ═══════════════════════════════════════════════════════════════════
# 6 · Missing tenant claim.
# ═══════════════════════════════════════════════════════════════════
def test_dry_run_rejects_request_with_no_tenant_scope(monkeypatch):
    """A JWT that omits every tenant claim (``tenant_id``,
    ``active_tenant_id``, ``_active_tenant_id_claim``) is
    rejected with 400 — the endpoint refuses to fall back to a
    global scan."""
    _two_tenant_db(monkeypatch)
    user_no_scope = {"id": "sa-x", "role": "super_admin"}
    with pytest.raises(HTTPException) as exc:
        _run(dr.data_repair_dry_run(user=user_no_scope))
    assert exc.value.status_code == 400
    assert "tenant" in str(exc.value.detail).lower()


# ═══════════════════════════════════════════════════════════════════
# 7 · Response body echoes tenant_id on both endpoints.
# ═══════════════════════════════════════════════════════════════════
def test_response_bodies_carry_tenant_id(monkeypatch):
    """Client can verify which tenant was scoped by reading the
    response payload — no more silent-global scans."""
    _two_tenant_db(monkeypatch)
    user_a = _sa(TENANT_A)
    dry = _run(dr.data_repair_dry_run(user=user_a))
    assert dry["tenant_id"] == TENANT_A

    body = dr.ApplyIn(
        confirm_token=dry["confirm_token"],
        dry_run_scan_timestamp=dry["scan_timestamp"],
    )
    apply_result = _run(dr.data_repair_apply(body, user=user_a))
    assert apply_result["tenant_id"] == TENANT_A


# ═══════════════════════════════════════════════════════════════════
# 8 · Cache isolation between tenants.
# ═══════════════════════════════════════════════════════════════════
def test_cache_slot_is_per_tenant(monkeypatch):
    """The 60-s dry-run cache must not leak tenant A's payload to
    tenant B.  Two back-to-back calls from different tenants must
    return different confirm_tokens and different tenant_id
    values."""
    _two_tenant_db(monkeypatch)
    a = _run(dr.data_repair_dry_run(user=_sa(TENANT_A, uid="sa-A")))
    b = _run(dr.data_repair_dry_run(user=_sa(TENANT_B, uid="sa-B")))
    assert a["tenant_id"] == TENANT_A
    assert b["tenant_id"] == TENANT_B
    assert a["confirm_token"] != b["confirm_token"]
    assert a["scan_timestamp"] != b["scan_timestamp"] or a["confirm_token"] != b["confirm_token"]


# ═══════════════════════════════════════════════════════════════════
# 9 · Non-super_admin rejection preserved.
# ═══════════════════════════════════════════════════════════════════
def test_non_super_admin_rejected_pre_tenant_check():
    """The router dependency ``require_super_admin`` rejects any
    non-super_admin role before the tenant-scope logic runs.  We
    pin the existing 403 behavior against role tampering."""
    from utils import require_super_admin
    for role in ("admin", "manager", "technician", "customer", None):
        user = {"id": "u1", "role": role, "tenant_id": TENANT_A}
        with pytest.raises(HTTPException) as exc:
            require_super_admin(user=user)
        assert exc.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# 10 · Live-id helpers are tenant-scoped in isolation.
# ═══════════════════════════════════════════════════════════════════
def test_live_customer_ids_are_tenant_scoped(monkeypatch):
    fake = _two_tenant_db(monkeypatch)
    assert _run(dr._live_customer_ids(TENANT_A)) == {"cA-live"}
    assert _run(dr._live_customer_ids(TENANT_B)) == {"cB-live"}
    # Non-existent tenant returns empty set — never a global set.
    assert _run(dr._live_customer_ids("ghost-tenant")) == set()


def test_live_technician_ids_are_tenant_scoped(monkeypatch):
    fake = _two_tenant_db(monkeypatch)
    # Add a users row per tenant.
    fake.users.rows.extend([
        {"id": "u-a-tech", "tenant_id": TENANT_A, "role": "technician"},
        {"id": "u-b-tech", "tenant_id": TENANT_B, "role": "technician"},
    ])
    assert _run(dr._live_technician_ids(TENANT_A)) == {"techA-live", "u-a-tech"}
    assert _run(dr._live_technician_ids(TENANT_B)) == {"techB-live", "u-b-tech"}
