"""Phase P12 · Feb-2026 — Route Optimizer soft-guard + $or-clobber fix.

Locks in the 5 backend acceptance points:

  1. A job stamped with an orphaned ``technician_id`` (references a
     ``users`` row that doesn't exist) rides the optimize call as-is
     — HTTP 200, job included in ``ordered_job_ids``, top-level
     ``orphaned_tech_ids`` non-empty.
  2. A job with NO ``technician_id`` at all is skipped from the
     optimizer input and returned under ``skipped_unassigned`` —
     HTTP 200, everything else optimized.
  3. A pure-clean batch returns HTTP 200 with empty
     ``orphaned_tech_ids`` and empty ``skipped_unassigned``.
  4. A technician-role caller is silently pinned to self (P9
     preserved — the existing hard-403 dispatcher-only guard fires).
  5. Cross-tenant tech_id / user_id → 403 (preserved).

Also indirectly locks in that the P12 ``$or``-clobber fix in
``route_optimization.py`` doesn't break existing behavior — every
test seeds a real job on ``scheduled_date`` only (no
``scheduled_start``), which the pre-P12 clobbered query silently
degraded to "any tenant job on this date" — the clean test would
have accidentally picked up other tenants' jobs.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def aquaterra_tech_h() -> dict:
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def sunbelt_admin_h(dbc) -> dict:
    """Bootstrap a fresh cross-tenant admin for cross-tenant assertions.

    Preferred over the historical fixture that skipped on missing
    ``admin@sunbelt.com`` — that path silently disabled the
    cross-tenant acceptance test forever. Here we seed a scoped
    ``p12-cross-t-*`` tenant + admin at module setup, tear both down
    on module teardown, and hand back an ``Authorization`` header.
    Reusing an existing admin from another tenant would work too but
    couples this test to whatever else that tenant is doing.
    """
    import bcrypt
    tid = "p12-cross-t-" + uuid.uuid4().hex[:8]
    email = f"admin+{tid}@p12.example"
    uid = str(uuid.uuid4())
    pw_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt(rounds=4)).decode()
    dbc.tenants.insert_one({
        "id": tid, "name": "P12 Cross-Tenant", "slug": tid,
        "active": True,
    })
    dbc.users.insert_one({
        "id": uid, "email": email, "password_hash": pw_hash,
        "tenant_id": tid, "role": "admin",
        "name": "P12 Cross-Tenant Admin",
        "is_active": True,
    })
    try:
        tok = _login(email, "password123")["access_token"]
        yield {"Authorization": f"Bearer {tok}"}
    finally:
        dbc.users.delete_one({"id": uid})
        dbc.tenants.delete_one({"id": tid})


@pytest.fixture
def _cleanup(dbc):
    """Track (id, tenant_id) tuples and drop them on teardown."""
    bag: list[tuple[str, str]] = []
    yield bag
    if bag:
        ids = [t[0] for t in bag]
        # Best-effort tenant-scoped delete for every tracked job.
        for jid, tid in bag:
            dbc.jobs.delete_one({"id": jid, "tenant_id": tid})


# ── 1) Orphaned technician_id → HTTP 200 with orphaned_tech_ids ─────
def test_p12_optimize_batch_with_orphaned_tech_returns_200_with_warning(
    aquaterra_admin_h, dbc, _cleanup,
):
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    assert mike, "mike@aquaterra.com missing from seed"
    tenant_id = mike["tenant_id"]

    day = "2026-09-16"
    # Seed one clean job on Mike + one orphan job on Mike's lane
    # (matches via ``assigned_technician_id``; the ``technician_id``
    # points at a fake id that doesn't resolve to any users/technicians
    # row). Both carry ``scheduled_date`` only.
    clean_jid = str(uuid.uuid4())
    orphan_jid = str(uuid.uuid4())
    orphan_tech_id = "ORPHAN-P12-{}".format(uuid.uuid4().hex[:8])

    dbc.jobs.insert_one({
        "id": clean_jid, "tenant_id": tenant_id,
        "technician_id": mike["id"],
        "title": "p12-clean-under-orphan-batch",
        "status": "scheduled",
        "scheduled_date": day,
        "site_lat": 33.73, "site_lng": -112.20,
        "address": "clean p12 st",
    })
    _cleanup.append((clean_jid, tenant_id))
    dbc.jobs.insert_one({
        "id": orphan_jid, "tenant_id": tenant_id,
        "technician_id": orphan_tech_id,
        "assigned_technician_id": mike["id"],
        "title": "p12-orphan-tech-id",
        "status": "scheduled",
        "scheduled_date": day,
        "site_lat": 33.74, "site_lng": -112.20,
        "address": "orphan p12 st",
    })
    _cleanup.append((orphan_jid, tenant_id))

    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=aquaterra_admin_h,
        json={"technician_id": mike["id"], "date": day},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:400]
    out = r.json()
    # Both jobs made it into the optimizer's output.
    ordered = out.get("ordered_job_ids") or []
    assert clean_jid in ordered, f"clean job missing from output: {ordered}"
    assert orphan_jid in ordered, f"orphan job missing from output: {ordered}"
    # Top-level P12 soft-guard surface exposes the orphan.
    assert orphan_tech_id in (out.get("orphaned_tech_ids") or []), (
        f"orphaned_tech_ids missing {orphan_tech_id}: "
        f"{out.get('orphaned_tech_ids')}"
    )
    # No accidental leakage into skipped_unassigned — this job DID
    # have a technician_id, just an orphaned one.
    assert orphan_jid not in (out.get("skipped_unassigned") or [])
    # Human-readable warning line rides ``warnings`` for existing
    # ORION-banner clients.
    assert any("orphan" in (w or "").lower()
                for w in (out.get("warnings") or []))


# ── 2) Unassigned job (no technician_id) → skipped_unassigned ───────
def test_p12_unassigned_job_skipped_not_rejected(
    aquaterra_admin_h, dbc, _cleanup,
):
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    assert mike, "mike@aquaterra.com missing from seed"
    tenant_id = mike["tenant_id"]

    day = "2026-09-17"
    clean_jid = str(uuid.uuid4())
    unassigned_jid = str(uuid.uuid4())

    dbc.jobs.insert_one({
        "id": clean_jid, "tenant_id": tenant_id,
        "technician_id": mike["id"],
        "title": "p12-clean-under-unassigned-batch",
        "status": "scheduled",
        "scheduled_date": day,
        "site_lat": 33.75, "site_lng": -112.20,
        "address": "clean p12 st",
    })
    _cleanup.append((clean_jid, tenant_id))
    # No ``technician_id`` on the second job — it only matches Mike's
    # lane via ``assigned_technician_id`` and MUST be skipped, not 4xx'd.
    dbc.jobs.insert_one({
        "id": unassigned_jid, "tenant_id": tenant_id,
        "assigned_technician_id": mike["id"],
        "title": "p12-no-technician-id",
        "status": "scheduled",
        "scheduled_date": day,
        "site_lat": 33.76, "site_lng": -112.20,
        "address": "unassigned p12 st",
    })
    _cleanup.append((unassigned_jid, tenant_id))

    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=aquaterra_admin_h,
        json={"technician_id": mike["id"], "date": day},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:400]
    out = r.json()
    ordered = out.get("ordered_job_ids") or []
    assert clean_jid in ordered
    assert unassigned_jid in (out.get("skipped_unassigned") or []), (
        f"unassigned job missing from skipped_unassigned: "
        f"{out.get('skipped_unassigned')}"
    )
    assert unassigned_jid not in ordered, (
        "unassigned job must not enter the optimizer input"
    )


# ── 3) Pure-clean batch → no warnings, no skips ─────────────────────
def test_p12_clean_batch_no_soft_guard_flags(
    aquaterra_admin_h, dbc, _cleanup,
):
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    assert mike, "mike@aquaterra.com missing from seed"
    tenant_id = mike["tenant_id"]

    day = "2026-09-18"
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    for jid, lat in ((a, 33.77), (b, 33.78)):
        dbc.jobs.insert_one({
            "id": jid, "tenant_id": tenant_id,
            "technician_id": mike["id"],
            "title": "p12-clean-batch",
            "status": "scheduled",
            "scheduled_date": day,
            "site_lat": lat, "site_lng": -112.20,
            "address": f"clean p12 {jid}",
        })
        _cleanup.append((jid, tenant_id))

    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=aquaterra_admin_h,
        json={"technician_id": mike["id"], "date": day},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:400]
    out = r.json()
    assert (out.get("orphaned_tech_ids") or []) == []
    assert (out.get("skipped_unassigned") or []) == []
    # Warnings list may carry algorithm-level notes (Haversine
    # fallback / ORION heuristics) but must NOT carry orphan lines.
    for w in (out.get("warnings") or []):
        assert "orphan" not in (w or "").lower()
        assert "no technician_id" not in (w or "").lower()


# ── 4) Technician-role caller is still gated (P9 preserved) ─────────
def test_p12_technician_role_pinned_to_self_p9_preserved(aquaterra_tech_h):
    """The Feb-2026 dispatcher-only guard hard-403s any tech caller —
    P9 pinning surfaces here as a hard rejection, which is the existing
    behavior the brief explicitly requires us to keep. If future work
    softens this to actual pinning, update this test in the same
    commit."""
    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=aquaterra_tech_h,
        json={"date": "2026-09-19"},
        timeout=15,
    )
    assert r.status_code == 403, (
        f"technician-role caller must be blocked (P9 dispatcher-only "
        f"gate), got {r.status_code} {r.text[:200]}"
    )


# ── 5) Cross-tenant tech_id → 403 (preserved) ───────────────────────
def test_p12_cross_tenant_target_is_rejected(sunbelt_admin_h, dbc):
    aqua_u = dbc.users.find_one({"email": "mike@aquaterra.com"})
    assert aqua_u, "expected mike@aquaterra.com to exist in seeded db"
    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=sunbelt_admin_h,
        json={"technician_id": aqua_u["id"], "date": "2026-09-20"},
        timeout=15,
    )
    # The existing guard is 403 "user_id not in current tenant" —
    # unchanged by P12.
    assert r.status_code == 403, r.text[:200]
    assert "not in current tenant" in r.text or "not found" in r.text
