"""POOL-A · Feb-2026 — Landscape exclusion from Pool Service Report.

Locks the thirteen invariants of Sub-phase A of the Pool Report
upgrade track (see ``memory/SPEC_POOL_REPORT_FILTER_FIX.md``):

    (a) 3 pool jobs + 2 landscape jobs → serviced count = 3.
    (b) service_type = "Pool Maintenance" →
        derive_industry_for_job == "pool".
    (c) service_type = "Landscaping" → "landscaping".
    (d) service_type = "Pool & Landscape Combo" → "landscaping"
        (explicit-exclusion-wins).
    (e) service_type = "landscape" (lowercase) → "landscaping"
        (case-insensitive).
    (f) service_type = "POOL" (uppercase) → "pool".
    (g) service_type = null → "other" (STRICT MODE — new POOL-A
        semantic; the non-strict default preserves the historical
        tenant-industry-fallback for existing consumers).
    (h) service_type = "Deck Cleaning" → "cleaning" (compound
        keyword `clean` hits, NOT "pool"; excluded from report).
    (i) compute_pool_service: tech with only landscape jobs →
        does NOT appear in report.
    (j) compute_pool_service: tech with mixed pool + landscape →
        appears with only pool-job counts.
    (k) compute_pool_service: tenant isolation preserved.
    (l) compute_pool_service: empty week → returns zeros, no crash.
    (m) compute_pool_service: totals == sum of per-tech values.

Uses the loop-consistent httpx-friendly pattern established by
test_lead_sense_intake.py — fresh Motor client bound to each
test's asyncio.run() loop so the shared config.db (module-import-
time-bound) doesn't cross-contaminate.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "POOLA_"


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    seeded_tenant_ids: List[str] = []
    seeded_job_ids: List[str] = []
    seeded_user_ids: List[str] = []
    yield seeded_tenant_ids, seeded_job_ids, seeded_user_ids
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
        "name": f"POOL-A seed tenant {tid[-8:]}",
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
        "role": "landscape_tech",
        "active": True,
    })
    return uid


def _seed_job(dbc, *, tenant_id: str, tech_id: str = None,
                 tech_name: str = None, service_type: Any = "Pool Cleaning",
                 status: str = "completed",
                 scheduled_date: str = None,
                 industry: str = None,
                 work_class: str = "service") -> str:
    jid = _fresh("JOB")
    row: Dict[str, Any] = {
        "id": jid,
        "tenant_id": tenant_id,
        "status": status,
        "scheduled_date": scheduled_date or "2026-02-16",
        # POOL-B · Feb-2026 — SPEC §280 backfill assumption: any
        # historical pool row missing ``work_class`` defaults to
        # ``"service"``.  Fixture seeds mirror that default so the
        # legacy POOL-A assertions on ``total_completed`` / row-
        # level ``completed`` count continue to pass after POOL-B
        # narrowed both to service-only.  Individual POOL-A tests
        # that need a repair / unknown row pass ``work_class=`` verbatim.
        "work_class": work_class,
    }
    if service_type is not None:
        row["service_type"] = service_type
    if tech_id:
        row["technician_id"] = tech_id
    if tech_name:
        row["technician_name"] = tech_name
    if industry:
        row["industry"] = industry
    dbc.jobs.insert_one(row)
    return jid


def _run(coro_factory):
    """Per-test fresh asyncio loop + Motor client bound to it.
    Motor futures land on the same loop the coroutine runs in →
    no ``Future attached to a different loop`` cross-contamination."""
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


# ═════════════════════════════════════════════════════════════════════
# derive_industry_for_job — direct helper tests (b/c/d/e/f/g/h)
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "service_type,expected",
    [
        ("Pool Maintenance", "pool"),           # (b)
        ("Landscaping", "landscaping"),          # (c)
        ("Pool & Landscape Combo", "landscaping"),  # (d) exclusion wins
        ("landscape", "landscaping"),           # (e) case-insensitive
        ("POOL", "pool"),                        # (f) uppercase
        ("Deck Cleaning", "cleaning"),           # (h)
        ("Chemical Treatment", "pool"),          # bonus — "chem" hit
        ("Lawn Mowing", "landscaping"),          # bonus — "mowing" hit
    ],
)
def test_helper_classifies_service_type(service_type, expected):
    from routers.industry_checklists import derive_industry_for_job
    got = derive_industry_for_job(
        {"service_type": service_type}, None, strict_mode=True,
    )
    assert got == expected, (
        f"service_type={service_type!r}: got {got!r}, "
        f"expected {expected!r}"
    )


def test_helper_null_service_type_strict_returns_other():
    """(g) — strict mode returns "other" on missing signal."""
    from routers.industry_checklists import derive_industry_for_job
    got = derive_industry_for_job(
        {"service_type": None}, {"industries": ["pool"]},
        strict_mode=True,
    )
    assert got == "other"


def test_helper_null_service_type_non_strict_falls_back_to_pool_tenant():
    """Regression guard — non-strict caller (industry checklist
    templates, chemistry gate, etc.) STILL sees the historical
    tenant-industry fallback. If this breaks, we've broken the
    contract with every other consumer of the helper."""
    from routers.industry_checklists import derive_industry_for_job
    got = derive_industry_for_job(
        {"service_type": None}, {"industries": ["pool"]},
    )
    assert got == "pool"


def test_helper_explicit_industry_override_wins():
    """A job with an explicit ``industry: "pool"`` field is a pool
    job even in strict mode — the priority chain in the helper
    respects explicit overrides."""
    from routers.industry_checklists import derive_industry_for_job
    got = derive_industry_for_job(
        {"service_type": None, "industry": "pool"},
        None, strict_mode=True,
    )
    assert got == "pool"


# ═════════════════════════════════════════════════════════════════════
# compute_pool_service — end-to-end aggregation tests (a/i/j/k/l/m)
# ═════════════════════════════════════════════════════════════════════
def test_a_three_pool_two_landscape_serviced_is_three(dbc, cleanup):
    """3 pool jobs + 2 landscape jobs by the same tech →
    total_completed == 3."""
    tids, _jids, _uids = cleanup
    tid = _seed_tenant(dbc)
    tids.append(tid)
    tech = _seed_tech(dbc, tenant_id=tid, name="Steven Martinez")
    week_start = "2026-02-16"
    for _ in range(3):
        _seed_job(dbc, tenant_id=tid, tech_id=tech,
                     tech_name="Steven Martinez",
                     service_type="Pool Cleaning",
                     scheduled_date=week_start)
    for _ in range(2):
        _seed_job(dbc, tenant_id=tid, tech_id=tech,
                     tech_name="Steven Martinez",
                     service_type="Landscaping",
                     scheduled_date=week_start)

    async def _apply(adb):
        from routers import jobs as _mod
        _mod._orig_db = getattr(_mod, "_orig_db", _mod.db)
        _mod.db = adb
        try:
            return await _mod.compute_pool_service(
                tid, date_from=week_start, date_to="2026-02-22",
            )
        finally:
            _mod.db = _mod._orig_db

    rep = _run(_apply)
    assert rep["total_completed"] == 3, (
        f"expected 3 pool jobs, got {rep!r}"
    )
    assert rep["total_skipped"] == 0
    # Steven appears with 3 completed, NOT 5.
    steven = next(r for r in rep["rows"]
                    if r.get("technician_id") == tech)
    assert steven["completed"] == 3
    assert steven["skipped"] == 0


def test_i_only_landscape_tech_absent_from_report(dbc, cleanup):
    """(i) — the original user pain: Steven with only landscape
    jobs must NOT appear on the report."""
    tids, _, _ = cleanup
    tid = _seed_tenant(dbc)
    tids.append(tid)
    steven = _seed_tech(dbc, tenant_id=tid, name="Steven Martinez")
    # Pool tech for a control comparison.
    dana = _seed_tech(dbc, tenant_id=tid, name="Dana Poolseeker")
    week_start = "2026-02-16"
    for _ in range(3):
        _seed_job(dbc, tenant_id=tid, tech_id=steven,
                     tech_name="Steven Martinez",
                     service_type="Landscape Maintenance",
                     scheduled_date=week_start)
    _seed_job(dbc, tenant_id=tid, tech_id=dana,
                 tech_name="Dana Poolseeker",
                 service_type="Pool Cleaning",
                 scheduled_date=week_start)

    async def _apply(adb):
        from routers import jobs as _mod
        _mod._orig_db = getattr(_mod, "_orig_db", _mod.db)
        _mod.db = adb
        try:
            return await _mod.compute_pool_service(
                tid, date_from=week_start, date_to="2026-02-22",
            )
        finally:
            _mod.db = _mod._orig_db

    rep = _run(_apply)
    tech_ids_on_report = {r.get("technician_id") for r in rep["rows"]}
    assert steven not in tech_ids_on_report, (
        f"Steven should NOT appear on the pool report — "
        f"rows={rep['rows']!r}"
    )
    assert dana in tech_ids_on_report
    assert rep["total_completed"] == 1


def test_j_mixed_tech_shows_only_pool_counts(dbc, cleanup):
    """(j) — a tech with both pool + landscape jobs appears with
    ONLY the pool counts in their bucket."""
    tids, _, _ = cleanup
    tid = _seed_tenant(dbc)
    tids.append(tid)
    tech = _seed_tech(dbc, tenant_id=tid, name="Mixed Marcus")
    week_start = "2026-02-16"
    for _ in range(4):
        _seed_job(dbc, tenant_id=tid, tech_id=tech,
                     tech_name="Mixed Marcus",
                     service_type="Pool Cleaning",
                     scheduled_date=week_start)
    for _ in range(3):
        _seed_job(dbc, tenant_id=tid, tech_id=tech,
                     tech_name="Mixed Marcus",
                     service_type="Landscape Design",
                     scheduled_date=week_start)
    # And a "Pool & Landscape Combo" — exclusion wins, should NOT
    # count on the pool side.
    _seed_job(dbc, tenant_id=tid, tech_id=tech,
                 tech_name="Mixed Marcus",
                 service_type="Pool & Landscape Combo",
                 scheduled_date=week_start)

    async def _apply(adb):
        from routers import jobs as _mod
        _mod._orig_db = getattr(_mod, "_orig_db", _mod.db)
        _mod.db = adb
        try:
            return await _mod.compute_pool_service(
                tid, date_from=week_start, date_to="2026-02-22",
            )
        finally:
            _mod.db = _mod._orig_db

    rep = _run(_apply)
    marcus = next(r for r in rep["rows"]
                    if r.get("technician_id") == tech)
    assert marcus["completed"] == 4, (
        f"expected 4 pool completions (landscape+combo excluded), "
        f"got {marcus!r}"
    )


def test_k_tenant_isolation_preserved(dbc, cleanup):
    """(k) — tenant A's report never counts tenant B's jobs."""
    tids, _, _ = cleanup
    tid_a = _seed_tenant(dbc)
    tid_b = _seed_tenant(dbc)
    tids.extend([tid_a, tid_b])
    tech_a = _seed_tech(dbc, tenant_id=tid_a, name="A Tech")
    tech_b = _seed_tech(dbc, tenant_id=tid_b, name="B Tech")
    week_start = "2026-02-16"
    _seed_job(dbc, tenant_id=tid_a, tech_id=tech_a,
                 tech_name="A Tech", service_type="Pool Cleaning",
                 scheduled_date=week_start)
    _seed_job(dbc, tenant_id=tid_b, tech_id=tech_b,
                 tech_name="B Tech", service_type="Pool Cleaning",
                 scheduled_date=week_start)

    async def _apply(adb):
        from routers import jobs as _mod
        _mod._orig_db = getattr(_mod, "_orig_db", _mod.db)
        _mod.db = adb
        try:
            return await _mod.compute_pool_service(
                tid_a, date_from=week_start, date_to="2026-02-22",
            )
        finally:
            _mod.db = _mod._orig_db

    rep = _run(_apply)
    tech_ids_on_report = {r.get("technician_id") for r in rep["rows"]}
    assert tech_a in tech_ids_on_report
    assert tech_b not in tech_ids_on_report, (
        "tenant B's tech must never appear on tenant A's report"
    )
    assert rep["total_completed"] == 1


def test_l_empty_week_returns_zeros(dbc, cleanup):
    """(l) — empty period returns zeros with no crash."""
    tids, _, _ = cleanup
    tid = _seed_tenant(dbc)
    tids.append(tid)

    async def _apply(adb):
        from routers import jobs as _mod
        _mod._orig_db = getattr(_mod, "_orig_db", _mod.db)
        _mod.db = adb
        try:
            return await _mod.compute_pool_service(
                tid, date_from="2026-02-16", date_to="2026-02-22",
            )
        finally:
            _mod.db = _mod._orig_db

    rep = _run(_apply)
    assert rep["total_completed"] == 0
    assert rep["total_skipped"] == 0
    assert rep["rows"] == []


def test_m_totals_match_sum_of_rows(dbc, cleanup):
    """(m) — totals in the response envelope equal the sum of
    per-technician values."""
    tids, _, _ = cleanup
    tid = _seed_tenant(dbc)
    tids.append(tid)
    a = _seed_tech(dbc, tenant_id=tid, name="Tech A")
    b = _seed_tech(dbc, tenant_id=tid, name="Tech B")
    week_start = "2026-02-16"
    for _ in range(4):
        _seed_job(dbc, tenant_id=tid, tech_id=a,
                     tech_name="Tech A", service_type="Pool Cleaning",
                     scheduled_date=week_start)
    for _ in range(2):
        _seed_job(dbc, tenant_id=tid, tech_id=b,
                     tech_name="Tech B", service_type="Pool Cleaning",
                     scheduled_date=week_start)
    _seed_job(dbc, tenant_id=tid, tech_id=b,
                 tech_name="Tech B", service_type="Pool Cleaning",
                 status="skipped", scheduled_date=week_start)
    # A landscape job that must not affect totals.
    _seed_job(dbc, tenant_id=tid, tech_id=a,
                 tech_name="Tech A", service_type="Landscape Design",
                 scheduled_date=week_start)

    async def _apply(adb):
        from routers import jobs as _mod
        _mod._orig_db = getattr(_mod, "_orig_db", _mod.db)
        _mod.db = adb
        try:
            return await _mod.compute_pool_service(
                tid, date_from=week_start, date_to="2026-02-22",
            )
        finally:
            _mod.db = _mod._orig_db

    rep = _run(_apply)
    assert rep["total_completed"] == sum(
        r["completed"] for r in rep["rows"]
    )
    assert rep["total_skipped"] == sum(
        r["skipped"] for r in rep["rows"]
    )
    assert rep["total_completed"] == 6
    assert rep["total_skipped"] == 1
