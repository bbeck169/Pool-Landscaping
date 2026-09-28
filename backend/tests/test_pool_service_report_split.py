"""POOL-B · Feb-2026 — Pool Service Report service/repair split.

Locks the invariants added by Sub-phase B of the pool-report
upgrade track:

  1. ``compute_pool_service`` splits completed pool jobs into
     three buckets by ``work_class``:
       * ``service`` → ``pools_serviced`` (maintenance)
       * ``repair``  → ``repairs_completed``
       * anything else (null / missing / unrecognised) → ``other``
  2. Landscape jobs (POOL-A filter) never enter ANY bucket —
     regression coverage for POOL-A inside POOL-B.
  3. Legacy top-level ``visits`` key is populated (concat of the
     three bucketed row lists) for backward-compat.
  4. Response shape is stable — no missing keys and every new key
     is present.
  5. The SPEC-preferred ``by_technician`` + ``totals`` blocks
     coexist with the brief-preferred ``summary`` + bucket arrays.

Uses the same fresh-loop Motor pattern as ``test_pool_report_filter.py``
so parallel test runs don't cross-contaminate the shared ``config.db``.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "POOLB_"


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    seeded_tenant_ids: List[str] = []
    yield seeded_tenant_ids
    if seeded_tenant_ids:
        dbc.tenants.delete_many({"id": {"$in": seeded_tenant_ids}})
        dbc.jobs.delete_many({"tenant_id": {"$in": seeded_tenant_ids}})
        dbc.users.delete_many({"tenant_id": {"$in": seeded_tenant_ids}})


def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_tenant(dbc, *, industries: List[str] = None) -> str:
    tid = _fresh("TEN")
    dbc.tenants.insert_one({
        "id": tid,
        "name": f"POOL-B seed tenant {tid[-8:]}",
        "industries": industries or ["pool"],
        "created_at": "2026-02-15T00:00:00Z",
    })
    return tid


def _seed_tech(dbc, *, tenant_id: str, name: str) -> str:
    uid = _fresh("TECH")
    dbc.users.insert_one({
        "id": uid,
        "tenant_id": tenant_id,
        "name": name,
        "role": "pool_tech",
        "active": True,
    })
    return uid


def _seed_job(dbc, *, tenant_id: str, tech_id: str = None,
                 tech_name: str = None, service_type: Any = "Pool Cleaning",
                 status: str = "completed",
                 scheduled_date: str = "2026-02-16",
                 work_class: Any = None,
                 industry: str = None) -> str:
    jid = _fresh("JOB")
    row: Dict[str, Any] = {
        "id": jid,
        "tenant_id": tenant_id,
        "status": status,
        "scheduled_date": scheduled_date,
    }
    if service_type is not None:
        row["service_type"] = service_type
    if tech_id:
        row["technician_id"] = tech_id
    if tech_name:
        row["technician_name"] = tech_name
    if industry:
        row["industry"] = industry
    # NB — ``work_class`` intentionally passed as-is (may be None
    # or a nonsense string) so the "other" bucket is exercised.
    if work_class is not None or work_class is None:
        row["work_class"] = work_class
    dbc.jobs.insert_one(row)
    return jid


def _run(coro_factory):
    """Fresh Motor client bound to a fresh asyncio loop — mirrors
    the pattern in test_pool_report_filter.py so parallel test
    runs never share a Motor client / loop across tests."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    try:
        return loop.run_until_complete(coro_factory(adb))
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


def _call_compute(tid: str, week_start: str, week_end: str):
    async def _apply(adb):
        from routers import jobs as _mod
        _mod._orig_db = getattr(_mod, "_orig_db", _mod.db)
        _mod.db = adb
        try:
            return await _mod.compute_pool_service(
                tid, date_from=week_start, date_to=week_end,
            )
        finally:
            _mod.db = _mod._orig_db
    return _run(_apply)


# ═════════════════════════════════════════════════════════════════════
# Split invariants
# ═════════════════════════════════════════════════════════════════════
def test_maintenance_repair_other_buckets_split_correctly(dbc, cleanup):
    """3 pool jobs (1 service, 1 repair, 1 unknown work_class) +
    2 landscape jobs (1 service, 1 repair) →
    maintenance=1, repairs=1, other=1, landscape count across all
    buckets = 0."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    tech = _seed_tech(dbc, tenant_id=tid, name="Steven Martinez")
    week_start = "2026-02-16"

    # Pool + service_type=Pool → maintenance bucket.
    _seed_job(dbc, tenant_id=tid, tech_id=tech,
                 tech_name="Steven Martinez",
                 service_type="Pool Cleaning",
                 work_class="service",
                 scheduled_date=week_start)
    # Pool + repair → repairs bucket.
    _seed_job(dbc, tenant_id=tid, tech_id=tech,
                 tech_name="Steven Martinez",
                 service_type="Pool Pump Repair",
                 work_class="repair",
                 scheduled_date=week_start)
    # Pool + null work_class → other bucket (SPEC ruling §274).
    _seed_job(dbc, tenant_id=tid, tech_id=tech,
                 tech_name="Steven Martinez",
                 service_type="Pool Inspection",
                 work_class=None,
                 scheduled_date=week_start)
    # Landscape + service → excluded (POOL-A).
    _seed_job(dbc, tenant_id=tid, tech_id=tech,
                 tech_name="Steven Martinez",
                 service_type="Landscaping",
                 work_class="service",
                 scheduled_date=week_start)
    # Landscape + repair → excluded (POOL-A).
    _seed_job(dbc, tenant_id=tid, tech_id=tech,
                 tech_name="Steven Martinez",
                 service_type="Landscape Cleanup",
                 work_class="repair",
                 scheduled_date=week_start)

    rep = _call_compute(tid, week_start, "2026-02-22")

    # ─── summary counts ──────────────────────────────────────────
    summary = rep["summary"]
    assert summary["maintenance_visits"] == 1, summary
    assert summary["repair_visits"] == 1, summary
    assert summary["other_visits"] == 1, summary
    assert summary["total_pool_visits"] == 3, summary

    # SPEC-preferred aliases in totals.
    assert rep["totals"]["pools_serviced"] == 1
    assert rep["totals"]["repairs_completed"] == 1

    # ─── landscape count across every bucket ── must be zero ─────
    for bucket_name in ("maintenance", "repairs", "other", "visits",
                          "by_technician"):
        for row in rep[bucket_name]:
            assert "Landscape" not in (row.get("technician_name") or "")
    # Steven appears in each bucket with the right counter.
    steven = next(r for r in rep["by_technician"]
                    if r["technician_id"] == tech)
    assert steven["pools_serviced"] == 1, steven
    assert steven["repairs_completed"] == 1, steven
    assert steven["other"] == 1, steven

    # ─── legacy top-level ``visits`` is populated ────────────────
    # It's the concat of the three bucket lists.  Steven appears in
    # all three buckets, so the concat has three entries (one per
    # bucket) — same tech, three references.
    assert len(rep["visits"]) == 3, rep["visits"]

    # ─── legacy total_completed narrowed to service-only ─────────
    # SPEC §200: a repair no longer inflates "total_completed".
    assert rep["total_completed"] == 1, (
        f"total_completed must reflect pools_serviced only, got {rep['total_completed']}"
    )


def test_response_shape_stable_no_missing_keys(dbc, cleanup):
    """Regression: every documented key is present on an empty
    tenant response too (no missing keys, no spurious keys the
    FE contract can't parse)."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)

    rep = _call_compute(tid, "2026-02-16", "2026-02-22")

    _expected = {
        # Legacy
        "week_start", "week_end", "total_completed", "total_skipped", "rows",
        # Brief additions
        "period", "summary", "maintenance", "repairs", "other", "visits",
        # SPEC additions
        "totals", "by_technician",
    }
    assert _expected.issubset(rep.keys()), (
        f"missing keys: {_expected - set(rep.keys())}"
    )
    # Summary sub-dict shape.
    _summary_keys = {"total_pool_visits", "maintenance_visits",
                       "repair_visits", "other_visits"}
    assert _summary_keys.issubset(rep["summary"].keys())
    # totals sub-dict shape.
    assert {"pools_serviced", "repairs_completed"}.issubset(
        rep["totals"].keys(),
    )


def test_pool_work_class_service_lands_in_maintenance(dbc, cleanup):
    """POOL-B: pool + work_class=service → ONLY in maintenance."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    tech = _seed_tech(dbc, tenant_id=tid, name="Maint Alice")
    _seed_job(dbc, tenant_id=tid, tech_id=tech, tech_name="Maint Alice",
                 service_type="Pool Cleaning", work_class="service")

    rep = _call_compute(tid, "2026-02-16", "2026-02-22")

    assert rep["summary"]["maintenance_visits"] == 1
    assert rep["summary"]["repair_visits"] == 0
    assert rep["summary"]["other_visits"] == 0
    assert len(rep["maintenance"]) == 1
    assert rep["maintenance"][0]["technician_id"] == tech
    assert len(rep["repairs"]) == 0
    assert len(rep["other"]) == 0


def test_pool_work_class_repair_lands_in_repairs(dbc, cleanup):
    """POOL-B: pool + work_class=repair → ONLY in repairs."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    tech = _seed_tech(dbc, tenant_id=tid, name="Repair Bob")
    _seed_job(dbc, tenant_id=tid, tech_id=tech, tech_name="Repair Bob",
                 service_type="Pool Pump Repair", work_class="repair")

    rep = _call_compute(tid, "2026-02-16", "2026-02-22")

    assert rep["summary"]["maintenance_visits"] == 0
    assert rep["summary"]["repair_visits"] == 1
    assert rep["summary"]["other_visits"] == 0
    assert len(rep["repairs"]) == 1
    assert rep["repairs"][0]["technician_id"] == tech
    assert len(rep["maintenance"]) == 0
    assert len(rep["other"]) == 0


def test_pool_null_or_unknown_work_class_lands_in_other(dbc, cleanup):
    """POOL-B ruling §274 — jobs where ``work_class`` is null,
    missing, or an unrecognised string like ``"inspection"`` fall
    into the ``other`` bucket, NOT ``maintenance``.  Locks the
    intentional divergence from ``services.work_class.infer_work_class``
    (which reads missing as ``"service"``)."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    tech = _seed_tech(dbc, tenant_id=tid, name="Unknown Uma")
    # None
    _seed_job(dbc, tenant_id=tid, tech_id=tech, tech_name="Unknown Uma",
                 service_type="Pool Inspection", work_class=None)
    # Unrecognised
    _seed_job(dbc, tenant_id=tid, tech_id=tech, tech_name="Unknown Uma",
                 service_type="Pool Assessment", work_class="inspection")

    rep = _call_compute(tid, "2026-02-16", "2026-02-22")

    assert rep["summary"]["maintenance_visits"] == 0
    assert rep["summary"]["repair_visits"] == 0
    assert rep["summary"]["other_visits"] == 2
    assert len(rep["other"]) == 1  # both jobs share the same tech
    assert rep["other"][0]["other"] == 2


def test_landscape_never_in_any_bucket_pool_a_regression(dbc, cleanup):
    """POOL-A regression inside POOL-B: a landscape job is
    filtered at the aggregation query and is invisible to the
    work_class split (would otherwise inflate ``other`` because
    landscape jobs typically don't stamp ``work_class``)."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    tech = _seed_tech(dbc, tenant_id=tid, name="Yardwork Yolanda")
    for _ in range(4):
        _seed_job(dbc, tenant_id=tid, tech_id=tech,
                     tech_name="Yardwork Yolanda",
                     service_type="Landscaping", work_class="service")
    for _ in range(3):
        _seed_job(dbc, tenant_id=tid, tech_id=tech,
                     tech_name="Yardwork Yolanda",
                     service_type="Lawn Mowing", work_class="repair")

    rep = _call_compute(tid, "2026-02-16", "2026-02-22")

    # No pool jobs — every bucket empty.
    assert rep["summary"]["maintenance_visits"] == 0
    assert rep["summary"]["repair_visits"] == 0
    assert rep["summary"]["other_visits"] == 0
    assert rep["summary"]["total_pool_visits"] == 0
    assert rep["maintenance"] == []
    assert rep["repairs"] == []
    assert rep["other"] == []
    assert rep["visits"] == []
    assert rep["by_technician"] == []
    # Yolanda never appears.
    for row in rep["rows"]:
        assert (row.get("technician_name") or "").lower() != "yardwork yolanda"


def test_tech_with_mixed_service_repair_appears_in_both_sections(dbc, cleanup):
    """A single tech doing both a maintenance visit AND a repair
    visit appears in the ``maintenance`` array (with pools_serviced=1)
    AND the ``repairs`` array (with repairs_completed=1)."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    tech = _seed_tech(dbc, tenant_id=tid, name="Mixed Marla")
    _seed_job(dbc, tenant_id=tid, tech_id=tech, tech_name="Mixed Marla",
                 service_type="Pool Cleaning", work_class="service")
    _seed_job(dbc, tenant_id=tid, tech_id=tech, tech_name="Mixed Marla",
                 service_type="Pool Pump Repair", work_class="repair")

    rep = _call_compute(tid, "2026-02-16", "2026-02-22")

    m_row = next(r for r in rep["maintenance"] if r["technician_id"] == tech)
    r_row = next(r for r in rep["repairs"] if r["technician_id"] == tech)
    assert m_row["pools_serviced"] == 1
    assert m_row["repairs_completed"] == 1  # counter still visible
    assert r_row["repairs_completed"] == 1
    assert r_row["pools_serviced"] == 1
    # But it's ONE tech underneath — same technician_id.
    assert m_row["technician_id"] == r_row["technician_id"]


def test_legacy_visits_top_level_is_populated(dbc, cleanup):
    """Brief mandate: keep legacy top-level ``visits`` key
    populated (concat of maintenance + repairs + other) for
    backward-compat with any consumer we haven't found yet."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)
    t1 = _seed_tech(dbc, tenant_id=tid, name="Alpha Ann")
    t2 = _seed_tech(dbc, tenant_id=tid, name="Beta Ben")
    _seed_job(dbc, tenant_id=tid, tech_id=t1, tech_name="Alpha Ann",
                 service_type="Pool Cleaning", work_class="service")
    _seed_job(dbc, tenant_id=tid, tech_id=t2, tech_name="Beta Ben",
                 service_type="Pool Pump Repair", work_class="repair")

    rep = _call_compute(tid, "2026-02-16", "2026-02-22")

    _concat = rep["maintenance"] + rep["repairs"] + rep["other"]
    assert rep["visits"] == _concat, "legacy ``visits`` must equal concat"
    assert len(rep["visits"]) == 2  # one per bucket
