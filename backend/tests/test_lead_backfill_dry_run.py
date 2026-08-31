"""Phase F5 · Feb-2026 — leads backfill dry-run + apply round-trip.

Seeds 3 empty "Website Visitor" leads with matching form
submissions, walks:

    plan → 3 candidates → apply → 3 changed → re-plan → 0 candidates.

Also covers the "no linked submission" skip path.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from services.migrations import leads_backfill_from_form_submissions_v1 as mig


class _FakeColl:
    def __init__(self, rows=None):
        self._rows: List[Dict[str, Any]] = list(rows or [])
        self.update_calls: List[Dict[str, Any]] = []
        self.insert_calls: List[Dict[str, Any]] = []

    async def find_one(self, q, projection=None):
        for r in self._rows:
            if _match(r, q):
                return dict(r)
        return None

    def find(self, q, projection=None):
        matched = [dict(r) for r in self._rows if _match(r, q)]
        return _FakeCursor(matched)

    async def update_one(self, q, upd):
        self.update_calls.append({"q": dict(q), "upd": dict(upd)})
        set_ops = upd.get("$set") or {}
        for r in self._rows:
            if _match(r, q):
                r.update(set_ops)
                break
        return type("R", (), {"matched_count": 1, "modified_count": 1})()

    async def insert_one(self, doc):
        self.insert_calls.append(dict(doc))
        self._rows.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("id")})()


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    async def to_list(self, n=None):
        return list(self._rows[:n]) if n else list(self._rows)


def _match(row, q):
    for k, v in q.items():
        if k == "$or":
            if not any(_match(row, sub) for sub in v):
                return False
            continue
        if k == "$and":
            if not all(_match(row, sub) for sub in v):
                return False
            continue
        cell = row.get(k)
        if isinstance(v, dict):
            if "$gte" in v and not (cell is not None and cell >= v["$gte"]):
                return False
            if "$lte" in v and not (cell is not None and cell <= v["$lte"]):
                return False
            if "$exists" in v:
                exists = k in row
                if exists != v["$exists"]:
                    return False
            continue
        if cell != v:
            return False
    return True


class _FakeDb:
    def __init__(self):
        self.leads = _FakeColl()
        self.form_submissions = _FakeColl()
        self.lead_backfill_events = _FakeColl()
        self.migration_status = _FakeColl()


def _iso(dt):
    return dt.isoformat()


def _seed_lead_pair(db, *, lead_id, sub_id, values,
                     lead_created_at, sub_created_at=None,
                     current_name="Website Visitor",
                     current_email="", current_phone=""):
    db.leads._rows.append({
        "id": lead_id,
        "tenant_id": "t-1",
        "name": current_name,
        "email": current_email,
        "phone": current_phone,
        "address": "",
        "created_at": lead_created_at,
    })
    db.form_submissions._rows.append({
        "id": sub_id,
        "tenant_id": "t-1",
        "form_id": "form-a",
        "values": values,
        "created_at": sub_created_at or lead_created_at,
    })


def test_plan_returns_would_change_count():
    db = _FakeDb()
    now = datetime.now(timezone.utc)
    _seed_lead_pair(db, lead_id="L1", sub_id="S1", lead_created_at=_iso(now),
                     values={"first_name": "Alice", "last_name": "Baker",
                              "email": "alice@example.com",
                              "cell_phone": "555-0001",
                              "city": "Peoria"})
    _seed_lead_pair(db, lead_id="L2", sub_id="S2",
                     lead_created_at=_iso(now - timedelta(minutes=5)),
                     values={"first_name": "Bob", "email": "bob@x.co"})
    _seed_lead_pair(db, lead_id="L3", sub_id="S3",
                     lead_created_at=_iso(now - timedelta(minutes=10)),
                     values={"full_name": "Carol", "phone": "555-0003"})
    result = asyncio.get_event_loop().run_until_complete(mig.plan(db))
    assert result["candidates_total"] == 3
    assert result["would_change"] == 3
    assert len(result["samples"]) == 3


def test_apply_repairs_leads_and_writes_audit_events():
    db = _FakeDb()
    now = datetime.now(timezone.utc)
    _seed_lead_pair(db, lead_id="L1", sub_id="S1", lead_created_at=_iso(now),
                     values={"first_name": "Alice", "last_name": "Baker",
                              "email": "alice@example.com",
                              "cell_phone": "555-0001", "city": "Peoria",
                              "state": "AZ", "zip": "85383",
                              "company_name": "Acme LLC"})
    r = asyncio.get_event_loop().run_until_complete(
        mig.apply_backfill(db, rate_limit_per_sec=0),
    )
    assert r["candidates_total"] == 1
    assert r["changed"] == 1
    assert r["skipped"] == 0
    # Verify the lead row is now hydrated.
    updated = db.leads._rows[0]
    assert updated["name"] == "Alice Baker"
    assert updated["email"] == "alice@example.com"
    assert updated["phone"] == "555-0001"
    assert updated["first_name"] == "Alice"
    assert updated["last_name"] == "Baker"
    assert updated["city"] == "Peoria"
    assert updated["state"] == "AZ"
    assert updated["zip"] == "85383"
    assert updated["company_name"] == "Acme LLC"
    # Audit event written.
    assert len(db.lead_backfill_events._rows) == 1
    ev = db.lead_backfill_events._rows[0]
    assert ev["lead_id"] == "L1"
    assert ev["submission_id"] == "S1"
    assert "name" in ev["after"]
    assert ev["before"]["name"] == "Website Visitor"


def test_apply_is_idempotent_second_run_zero_changes():
    db = _FakeDb()
    now = datetime.now(timezone.utc)
    _seed_lead_pair(db, lead_id="L1", sub_id="S1", lead_created_at=_iso(now),
                     values={"first_name": "Alice", "last_name": "Baker",
                              "email": "alice@example.com"})
    asyncio.get_event_loop().run_until_complete(
        mig.apply_backfill(db, rate_limit_per_sec=0),
    )
    r2 = asyncio.get_event_loop().run_until_complete(
        mig.apply_backfill(db, rate_limit_per_sec=0),
    )
    # The lead is no longer a "Website Visitor" so it's not in the candidates.
    assert r2["candidates_total"] == 0
    assert r2["changed"] == 0


def test_lead_with_no_matching_submission_is_skipped():
    db = _FakeDb()
    now = datetime.now(timezone.utc)
    # Lead but NO submission within the ±60s window.
    db.leads._rows.append({
        "id": "L-orphan", "tenant_id": "t-1",
        "name": "Website Visitor", "email": "", "phone": "",
        "created_at": _iso(now),
    })
    r = asyncio.get_event_loop().run_until_complete(
        mig.apply_backfill(db, rate_limit_per_sec=0),
    )
    assert r["changed"] == 0
    assert r["skipped"] == 1


def test_ambiguous_multi_submission_window_is_skipped():
    """>1 submission inside the ±60s window → don't guess."""
    db = _FakeDb()
    now = datetime.now(timezone.utc)
    lead_ts = _iso(now)
    db.leads._rows.append({
        "id": "L1", "tenant_id": "t-1",
        "name": "Website Visitor", "email": "", "phone": "",
        "created_at": lead_ts,
    })
    db.form_submissions._rows.extend([
        {"id": "S1", "tenant_id": "t-1", "values": {"first_name": "A"},
         "created_at": lead_ts},
        {"id": "S2", "tenant_id": "t-1", "values": {"first_name": "B"},
         "created_at": _iso(now + timedelta(seconds=5))},
    ])
    r = asyncio.get_event_loop().run_until_complete(
        mig.apply_backfill(db, rate_limit_per_sec=0),
    )
    assert r["changed"] == 0
    assert r["skipped"] == 1
