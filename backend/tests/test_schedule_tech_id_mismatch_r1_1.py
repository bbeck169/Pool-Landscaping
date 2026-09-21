"""Phase R1.1 · Feb-2026 — Schedule 500 · technician_id mismatch hotfix.

The ``/schedule/today`` handler previously assumed every job's
``technician_id`` resolved to a live technician / user in the tenant.
Under the real ``jobs`` collection two id spaces co-exist
(``technicians.id`` post-K42 and ``users.id`` pre-K42), and orphaned /
soft-deleted techs leave ``jobs.technician_id`` pointing at ghost ids.
A downstream consumer that dereferenced the ghost id (or a strict
resolver in the projection loop) 500-ed the Schedule screen.

This suite pins the Phase R1.1 Safe Check:

* Two-fixture repro — one job whose ``technician_id`` resolves to a
  live tech in the tenant, one whose ``technician_id`` is a dangling
  ghost.  ``/schedule/today`` must return **200** with only the
  valid job in ``items`` AND emit a single WARN log for the skipped
  row (job_id + tenant_id + offending ``technician_id`` present in
  the record).
* Direct ``_live_technician_id_space`` helper coverage — tenant-
  scoped, both id spaces present, ghost ids excluded.
* ``_resolve_tech_display`` returns ``None`` on a ghost id (no
  raise) and never leaks cross-tenant names.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import pytest

from routers import schedule as sched


# ── Minimal Motor-compatible stubs (mirrors the R1 shape used in
# tests/test_data_repair_dry_run.py — kept self-contained here so
# this file has no test-file cross-imports).  Handles just the
# operators the schedule handler actually invokes.
class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])

    async def find_one(self, query, projection=None):  # noqa: ARG002
        for row in self.rows:
            if _matches(row, query):
                return dict(row)
        return None

    async def insert_one(self, doc):
        self.rows.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("id")})()

    async def update_one(self, filt, update):
        for row in self.rows:
            if _matches(row, filt):
                if "$set" in update:
                    row.update(update["$set"])
                if "$push" in update:
                    for k, v in update["$push"].items():
                        row.setdefault(k, []).append(v)
                return type("R", (), {"modified_count": 1})()
        return type("R", (), {"modified_count": 0})()

    async def count_documents(self, query):
        return sum(1 for r in self.rows if _matches(r, query))

    def find(self, query=None, projection=None):  # noqa: ARG002
        outer = self
        q = query or {}

        class _Cursor:
            def __init__(self):
                self._rows = [dict(r) for r in outer.rows if _matches(r, q)]

            def __aiter__(self):
                self._it = iter(self._rows)
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:
                    raise StopAsyncIteration

            def sort(self, *_a, **_k):
                return self

            async def to_list(self, _n=None):
                return list(self._rows)

        return _Cursor()

    def aggregate(self, *_a, **_k):
        return self.find({})


def _matches(row, query):
    for k, v in query.items():
        if k == "$or":
            if not any(_matches(row, sub) for sub in v):
                return False
            continue
        if k == "$and":
            if not all(_matches(row, sub) for sub in v):
                return False
            continue
        if isinstance(v, dict):
            if "$exists" in v:
                if v["$exists"] != (k in row):
                    return False
                continue
            if "$in" in v:
                if row.get(k) not in v["$in"]:
                    return False
                continue
            if "$gte" in v or "$lte" in v or "$lt" in v or "$gt" in v:
                val = row.get(k)
                if val is None:
                    return False
                if "$gte" in v and not (val >= v["$gte"]):
                    return False
                if "$lte" in v and not (val <= v["$lte"]):
                    return False
                if "$lt" in v and not (val < v["$lt"]):
                    return False
                if "$gt" in v and not (val > v["$gt"]):
                    return False
                continue
            if "$regex" in v:
                import re
                if not re.match(v["$regex"], str(row.get(k) or "")):
                    return False
                continue
            return False
        if row.get(k) != v:
            return False
    return True


class _DB:
    def __init__(self, jobs=None, customers=None, technicians=None,
                 users=None, crews=None, time_entries=None,
                 distance_matrix_cache=None):
        self.jobs = _Coll(jobs)
        self.customers = _Coll(customers)
        self.technicians = _Coll(technicians)
        self.users = _Coll(users)
        self.crews = _Coll(crews)
        self.time_entries = _Coll(time_entries)
        self.distance_matrix_cache = _Coll(distance_matrix_cache)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


TENANT = "t-r1-1"


def _make_request():
    """Return a FastAPI-compatible Request stub whose
    ``request.state.timings`` list absorbs the endpoint's
    Server-Timing appends without exercising Starlette internals."""
    class _State:
        def __init__(self):
            self.timings: list = []

    class _Req:
        def __init__(self):
            self.state = _State()

    return _Req()


# ═══════════════════════════════════════════════════════════════════
# 1 · Two-fixture repro — /schedule/today returns 200 with only the
#      valid job, WARN log emitted for the skipped dangling one.
# ═══════════════════════════════════════════════════════════════════
def test_schedule_today_skips_dangling_tech_ref_returns_200(monkeypatch, caplog):
    # Live technician + live user (both matching the same id-space so
    # both resolve via the R1.1 helper's cascade).
    tech = {"id": "tech-live-1", "tenant_id": TENANT}
    user = {"id": "u-tech-1", "tenant_id": TENANT, "role": "technician",
            "technician_id": "tech-live-1", "name": "Live Tech"}

    jobs = [
        # ── Valid — technician_id points at the live technician.
        {"id": "j-valid",
         "tenant_id": TENANT,
         "technician_id": "tech-live-1",
         "assigned_technician_id": "u-tech-1",
         "customer_id": "c1",
         "customer_name": "Valid Customer",
         "status": "scheduled",
         "scheduled_date": "2026-08-01"},
        # ── Dangling — matches visibility via ``assigned_technician_id``
        # but ``technician_id`` is a ghost that no longer resolves to
        # any tech / user in the tenant.  R1.1 Safe Check must skip
        # this row + WARN.
        {"id": "j-dangling",
         "tenant_id": TENANT,
         "technician_id": "GHOST-DELETED-TECH",
         "assigned_technician_id": "u-tech-1",
         "customer_id": "c1",
         "customer_name": "Dangling Customer",
         "status": "scheduled",
         "scheduled_date": "2026-08-01"},
    ]
    fake = _DB(jobs=jobs, customers=[{"id": "c1", "tenant_id": TENANT}],
                technicians=[tech], users=[user])
    monkeypatch.setattr(sched, "db", fake)

    tenant = {"id": TENANT, "timezone": "America/Phoenix"}
    with caplog.at_level(logging.WARNING, logger="server"):
        # Also match the ``config`` logger the router imports as
        # ``from config import db, logger``.
        with caplog.at_level(logging.WARNING):
            result = _run(sched.schedule_today(
                request=_make_request(),
                date="2026-08-01",
                user=user,
                tenant=tenant,
            ))

    # ── Response is 200 (function returns a dict, no exception).
    assert isinstance(result, dict)
    job_ids = [it["id"] for it in result["items"] if it["type"] == "job"]
    assert job_ids == ["j-valid"], (
        f"expected only j-valid in response items, got {job_ids}"
    )

    # ── WARN log contains the skipped job's job_id + tenant_id +
    # offending technician_id.
    warn_msgs = [rec.getMessage() for rec in caplog.records
                  if rec.levelno == logging.WARNING
                  and "dangling technician_id" in rec.getMessage()]
    assert warn_msgs, (
        "expected a WARN log for the skipped job; got: "
        + repr([r.getMessage() for r in caplog.records])
    )
    joined = " | ".join(warn_msgs)
    assert "j-dangling" in joined
    assert TENANT in joined
    assert "GHOST-DELETED-TECH" in joined


# ═══════════════════════════════════════════════════════════════════
# 2 · Live-tech id-space helper — tenant-scoped + unions both spaces.
# ═══════════════════════════════════════════════════════════════════
def test_live_technician_id_space_unions_both_id_spaces(monkeypatch):
    fake = _DB(
        jobs=[],
        technicians=[
            {"id": "tech-a", "tenant_id": TENANT, "user_id": "u-a"},
            {"id": "tech-b", "tenant_id": TENANT, "user_id": None},
            # Cross-tenant tech — MUST NOT bleed.
            {"id": "tech-other", "tenant_id": "other-tenant"},
        ],
        users=[
            {"id": "u-a", "tenant_id": TENANT, "role": "technician",
              "technician_id": "tech-a"},
            {"id": "u-mgr", "tenant_id": TENANT, "role": "manager"},
            {"id": "u-cust", "tenant_id": TENANT, "role": "customer"},
            # Cross-tenant user — MUST NOT bleed.
            {"id": "u-other", "tenant_id": "other-tenant",
              "role": "technician"},
        ],
    )
    monkeypatch.setattr(sched, "db", fake)

    ids = _run(sched._live_technician_id_space(TENANT))
    # Present:
    assert "tech-a" in ids
    assert "tech-b" in ids
    assert "u-a" in ids
    assert "u-mgr" in ids
    # NOT present — customer role is not a tech candidate.
    assert "u-cust" not in ids
    # NOT present — cross-tenant.
    assert "tech-other" not in ids
    assert "u-other" not in ids


# ═══════════════════════════════════════════════════════════════════
# 3 · Resolver returns None (never raises) on ghost id.
# ═══════════════════════════════════════════════════════════════════
def test_resolve_tech_display_returns_none_on_ghost(monkeypatch):
    fake = _DB(jobs=[], technicians=[
        {"id": "tech-a", "tenant_id": TENANT, "name": "Live Tech"},
    ], users=[])
    monkeypatch.setattr(sched, "db", fake)

    # Live id → resolves.
    got = _run(sched._resolve_tech_display(TENANT, "tech-a"))
    assert got == "Live Tech"

    # Ghost id → None, no raise.
    got = _run(sched._resolve_tech_display(TENANT, "GHOST-999"))
    assert got is None

    # None input → None, no raise.
    got = _run(sched._resolve_tech_display(TENANT, None))
    assert got is None


# ═══════════════════════════════════════════════════════════════════
# 4 · Resolver is tenant-scoped — never leaks cross-tenant names.
# ═══════════════════════════════════════════════════════════════════
def test_resolve_tech_display_does_not_leak_cross_tenant(monkeypatch):
    fake = _DB(jobs=[], technicians=[
        {"id": "tech-shared", "tenant_id": "other-tenant",
         "name": "Cross-Tenant Tech"},
    ], users=[])
    monkeypatch.setattr(sched, "db", fake)

    got = _run(sched._resolve_tech_display(TENANT, "tech-shared"))
    assert got is None
