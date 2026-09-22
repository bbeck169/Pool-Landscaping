"""Phase P22 · Feb-2026 · P0 PROD HOTFIX — Schedule truncation regression.

Locks the K15 300-row cap removal on tech/crew-scoped date-range reads.

Production regression: ``GET /api/jobs?technician_id=X&start=Y&end=Z``
was truncating at 300 rows when a tech pulled a multi-week schedule
window (Aquaterra prod symptom: "Schedule renders blank from Sep 22
onward" for tech Ethan). The K15 defensive cap unconditionally
clamped ``limit`` to 300 whenever ``technician_id`` or ``crew_id``
was in play, so the tail of a wider range silently fell off the end.

This suite exercises the endpoint via the direct ``list_jobs``
function-call harness (same pattern as ``test_jobs_crew_filter.py``)
because the F7 loop fixture is what the rest of the jobs tests use
— gives us deterministic seeds without a live uvicorn.

Points locked:
  1. Tech-scoped read with a 10-day window + 500 jobs returns ALL
     500 rows.
  2. Crew-scoped read with a 10-day window + 500 jobs returns ALL
     500 rows.
  3. Tech-scoped read with NO date range still applies a sane cap
     (1000, not 300) — proves the K15 300-row constant is gone.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from tests._f7_loop_fixture import run_test


TAG = "TEST_P22_"


async def _seed(db):
    tenant = await db.tenants.find_one(
        {"slug": "aquaterra"}, {"_id": 0, "id": 1},
    )
    tid = tenant["id"]
    admin = await db.users.find_one(
        {"email": "admin@aquaterra.com"},
        {"_id": 0, "id": 1, "role": 1, "tenant_id": 1},
    )
    return tid, admin


async def _cleanup(db, tid, tag_prefix):
    await db.jobs.delete_many({
        "tenant_id": tid, "id": {"$regex": f"^{tag_prefix}"},
    })
    await db.crews.delete_many({
        "tenant_id": tid, "id": {"$regex": f"^{tag_prefix}"},
    })


async def _seed_daily_jobs(db, tid, tech_id, crew_id, start_day, days, per_day):
    """Seed ``days * per_day`` jobs across a contiguous date window.

    ``scheduled_date`` is stored as a bare ``YYYY-MM-DD`` string so
    the fast path in the ``start`` / ``end`` filter matches directly
    (no tenant-tz union needed for the assertion).
    """
    docs = []
    for d in range(days):
        day = (start_day + timedelta(days=d)).strftime("%Y-%m-%d")
        for i in range(per_day):
            docs.append({
                "id": f"{TAG}{d:02d}_{i:03d}_{uuid.uuid4().hex[:6]}",
                "tenant_id": tid,
                "customer_id": "p22-fake",
                "status": "scheduled",
                "technician_id": tech_id,
                "crew_id": crew_id,
                "scheduled_date": day,
            })
    if docs:
        await db.jobs.insert_many(docs)


def _call(**overrides):
    """Explicit-kwargs direct call of ``list_jobs`` — sidesteps
    FastAPI's ``Query`` defaults for tests. See ``test_jobs_crew_filter.py``
    for the rationale (``Query()`` sentinels leak into BSON on direct
    calls). ``response`` defaults to ``None`` so the header write is a
    no-op in this path."""
    from routers.jobs import list_jobs
    kwargs = dict(
        status=None, technician_id=None,
        customer_id=None, crew_id=None,
        start=None, end=None,
        scheduled_date=None, recurring_template_id=None,
        limit=1000, include_deleted=False,
        include_photos=False, response=None,
    )
    kwargs.update(overrides)
    return list_jobs(**kwargs)


# ─── 1) Tech-scoped, date range, 500 rows across 10 days ──────────
def test_p22_tech_scoped_date_range_returns_all_rows_without_truncation():
    """The canonical prod regression net — 500 rows across a 10-day
    window under a tech scope must ALL come back. Pre-P22 this
    truncated at 300."""
    async def _go(db):
        tid, _admin = await _seed(db)
        await _cleanup(db, tid, TAG)
        tech_id = f"{TAG}TECH_{uuid.uuid4().hex[:6]}"
        crew_id = f"{TAG}CREW_{uuid.uuid4().hex[:6]}"
        start_day = datetime(2026, 2, 1, tzinfo=timezone.utc).date()
        await _seed_daily_jobs(
            db, tid, tech_id, crew_id,
            start_day=start_day, days=10, per_day=50,
        )
        # Admin caller so no role gate blocks; ``technician_id``
        # filter engages the K15 cap path.
        admin_user = {"id": "admin", "role": "admin", "tenant_id": tid}
        try:
            end_day = start_day + timedelta(days=9)
            res = await _call(
                user=admin_user, tenant={"id": tid},
                technician_id=tech_id,
                start=start_day.strftime("%Y-%m-%d"),
                end=end_day.strftime("%Y-%m-%d"),
            )
            p22_ids = [j["id"] for j in res if j["id"].startswith(TAG)]
            assert len(p22_ids) == 500, (
                f"P22 regression: tech-scoped date-range read "
                f"truncated at {len(p22_ids)}/500 rows"
            )
        finally:
            await _cleanup(db, tid, TAG)
    run_test(_go)


# ─── 2) Crew-scoped, date range, 500 rows across 10 days ──────────
def test_p22_crew_scoped_date_range_returns_all_rows_without_truncation():
    """Same guarantee for the crew-scope path — the K15 cap covered
    ``crew_id`` too."""
    async def _go(db):
        tid, _admin = await _seed(db)
        await _cleanup(db, tid, TAG)
        tech_id = f"{TAG}TECH_{uuid.uuid4().hex[:6]}"
        crew_id = f"{TAG}CREW_{uuid.uuid4().hex[:6]}"
        # Register the crew so the crew_id filter's tenant-scoped
        # lookup doesn't 404.
        await db.crews.insert_one({
            "id": crew_id, "tenant_id": tid,
            "name": "P22 test crew", "tech_ids": [tech_id],
        })
        start_day = datetime(2026, 3, 1, tzinfo=timezone.utc).date()
        await _seed_daily_jobs(
            db, tid, tech_id, crew_id,
            start_day=start_day, days=10, per_day=50,
        )
        admin_user = {"id": "admin", "role": "admin", "tenant_id": tid}
        try:
            end_day = start_day + timedelta(days=9)
            res = await _call(
                user=admin_user, tenant={"id": tid},
                crew_id=crew_id,
                start=start_day.strftime("%Y-%m-%d"),
                end=end_day.strftime("%Y-%m-%d"),
            )
            p22_ids = [j["id"] for j in res if j["id"].startswith(TAG)]
            assert len(p22_ids) == 500, (
                f"P22 regression: crew-scoped date-range read "
                f"truncated at {len(p22_ids)}/500 rows"
            )
        finally:
            await _cleanup(db, tid, TAG)
    run_test(_go)


# ─── 3) Tech-scoped, NO date range → sane cap at 1000 (was 300) ───
def test_p22_tech_scoped_no_date_range_caps_at_1000_not_300():
    """Defensive-path check — with no date range provided the K15
    branch still clamps, but the new floor is 1000 rows (was 300).
    We seed 500 rows so we can be sure the caller isn't hit by the
    old 300-clamp; the assertion is symmetric — all 500 must come
    back, and no more, because the seed is contiguous."""
    async def _go(db):
        tid, _admin = await _seed(db)
        await _cleanup(db, tid, TAG)
        tech_id = f"{TAG}TECH_{uuid.uuid4().hex[:6]}"
        crew_id = f"{TAG}CREW_{uuid.uuid4().hex[:6]}"
        start_day = datetime(2026, 4, 1, tzinfo=timezone.utc).date()
        # 500 rows, no date range in the request — this is the branch
        # that would have hit the old 300 cap. New behavior: 1000 cap,
        # so all 500 come back.
        await _seed_daily_jobs(
            db, tid, tech_id, crew_id,
            start_day=start_day, days=10, per_day=50,
        )
        admin_user = {"id": "admin", "role": "admin", "tenant_id": tid}
        try:
            res = await _call(
                user=admin_user, tenant={"id": tid},
                technician_id=tech_id,
                # NB: no ``start``, no ``end``, no ``scheduled_date``.
            )
            p22_ids = [j["id"] for j in res if j["id"].startswith(TAG)]
            assert len(p22_ids) == 500, (
                f"P22 regression: no-date-range tech read returned "
                f"{len(p22_ids)}/500 rows (old 300 cap must be gone)"
            )
        finally:
            await _cleanup(db, tid, TAG)
    run_test(_go)


# ─── 4) Source-lint — the 300-row constant is gone from jobs.py ──
def test_p22_source_lint_no_300_row_clamp():
    """Compile-time-ish guard so nobody silently re-introduces the
    ``limit = min(limit, 300)`` line the P22 fix removed. We grep
    the module for the literal call shape rather than the number
    ``300`` (which still legitimately appears in comments describing
    the removed behaviour)."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "routers" / "jobs.py"
    body = src.read_text(encoding="utf-8")
    assert "min(limit, 300)" not in body, (
        "P22 regression: ``min(limit, 300)`` re-introduced. The "
        "K15 clamp must stay at min(limit, 1000)."
    )
    # And the new 1000 clamp is present.
    assert "min(limit, 1000)" in body, (
        "P22 shape drift: expected ``min(limit, 1000)`` clamp on the "
        "no-date-range branch — got neither 300 nor 1000."
    )
