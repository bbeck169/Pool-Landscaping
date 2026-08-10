"""Phase 55-f · Aug-2026 — Homeworks importer commit engine + dry-run
+ progress + rollback-from-committed.

Reuses the ``_FakeColl`` / ``fake_db`` fixture pattern from the 55-a
scaffold test file, but adds ``properties`` alongside the two
collections the 55-a tests exercised so the commit engine has
somewhere to insert non-customer/non-job rows.
"""
from __future__ import annotations
import asyncio

import pytest


# ── Shared fake collection (mirrors 55-a scaffold test doubles) ──
class _DeleteResult:
    def __init__(self, n): self.deleted_count = n


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    @staticmethod
    def _match(d, q):
        for k, v in q.items():
            if d.get(k) != v:
                return False
        return True

    async def insert_one(self, d): self.docs.append(dict(d))

    async def find_one(self, q, projection=None):
        for d in self.docs:
            if self._match(d, q):
                return dict(d)
        return None

    def find(self, q, projection=None):
        matches = [dict(d) for d in self.docs if self._match(d, q)]
        return _Cur(matches)

    async def update_one(self, q, upd):
        for d in self.docs:
            if self._match(d, q):
                for k, v in (upd.get("$set") or {}).items():
                    d[k] = v
                return

    async def delete_many(self, q):
        keep, dropped = [], 0
        for d in self.docs:
            if self._match(d, q):
                dropped += 1
            else:
                keep.append(d)
        self.docs = keep
        return _DeleteResult(dropped)


class _Cur:
    def __init__(self, docs): self.docs = docs

    def sort(self, k, dir=1):
        rev = dir == -1
        self.docs = sorted(self.docs, key=lambda d: d.get(k) or "",
                             reverse=rev)
        return self

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self.docs):
            raise StopAsyncIteration
        d = self.docs[self._i]; self._i += 1
        return d


@pytest.fixture
def fake_db(monkeypatch):
    from config import db as _real
    batches = _FakeColl()
    staging = _FakeColl()
    customers = _FakeColl()
    properties = _FakeColl()
    jobs = _FakeColl()
    for name, coll in (("import_batches", batches),
                         ("homeworks_staging", staging),
                         ("customers", customers),
                         ("properties", properties),
                         ("jobs", jobs)):
        monkeypatch.setattr(_real, name, coll, raising=False)
    original_getitem = type(_real).__getitem__

    def _getitem(self, name):
        override = {"import_batches": batches,
                    "homeworks_staging": staging,
                    "customers": customers,
                    "properties": properties,
                    "jobs": jobs}
        if name in override:
            return override[name]
        return original_getitem(self, name)
    monkeypatch.setattr(type(_real), "__getitem__", _getitem)
    return {"batches": batches, "staging": staging,
            "customers": customers, "properties": properties,
            "jobs": jobs}


ADMIN = {"id": "u-a", "role": "admin", "tenant_id": "tenant-A"}
TENANT = {"id": "tenant-A"}


# ── Helpers ─────────────────────────────────────────────────────
def _seed_batch(fake, state="paused", **extra):
    doc = {"id": "b1", "tenant_id": "tenant-A", "state": state,
            "source": "copilot_crm",
            "entity_types_planned": ["customers", "jobs"],
            "entity_counts": {}, **extra}
    fake["batches"].docs.append(doc)
    return doc


def _seed_staging(fake, staging_id, entity_type, dedupe_status,
                   mapped, batch_id="b1", matched_target_id=None,
                   commit_error=None, imported_at=None):
    fake["staging"].docs.append({
        "id": staging_id, "tenant_id": "tenant-A",
        "batch_id": batch_id, "entity_type": entity_type,
        "dedupe_status": dedupe_status, "mapped_payload": mapped,
        "matched_target_id": matched_target_id,
        "imported_at": imported_at, "commit_error": commit_error,
        "homeworks_id": f"hw-{staging_id}",
    })


# ═══ Tests ══════════════════════════════════════════════════════
def test_dryrun_aggregates_entity_counts_and_flags_prior_errors(fake_db):
    async def _run():
        from routers.homeworks_import import dryrun_report
        _seed_batch(fake_db, state="paused")
        # 3 new customers, 1 matched customer, 1 conflict customer,
        # 2 new jobs.
        for i in range(3):
            _seed_staging(fake_db, f"sc-new-{i}", "customers",
                           "new", {"first_name": f"C{i}"})
        _seed_staging(fake_db, "sc-mat-0", "customers", "matched",
                       {"tags": ["Imported"]},
                       matched_target_id="c-existing")
        _seed_staging(fake_db, "sc-conf-0", "customers", "conflict",
                       {"first_name": "Conflict"})
        for i in range(2):
            _seed_staging(fake_db, f"sj-new-{i}", "jobs",
                           "new", {"title": f"J{i}", "customer_id": "c"})
        # One staging row already had a prior commit_error → warning.
        _seed_staging(fake_db, "sj-err", "jobs", "new",
                       {"title": "boom"},
                       commit_error="conn_refused",
                       imported_at="2026-08-01T00:00:00")

        r = await dryrun_report("b1", user=ADMIN, tenant=TENANT)
        assert r["batch_id"] == "b1"
        assert r["state"] == "paused"
        # Customers bucket: 3 new + 1 matched + 1 conflict → total 5.
        cust = r["entity_counts"]["customers"]
        assert cust == {"new": 3, "matched": 1, "conflict": 1,
                          "total": 5}
        # Jobs bucket: 3 new (2 unprocessed + 1 errored) → total 3.
        jobs = r["entity_counts"]["jobs"]
        assert jobs["new"] == 3 and jobs["total"] == 3
        # Warning surfaced for the prior-error row.
        assert any(w["type"] == "prior_commit_error"
                    and w["staging_id"] == "sj-err"
                    for w in r["warnings"])

    asyncio.run(_run())


def test_commit_new_only_inserts_with_import_batch_id(fake_db):
    async def _run():
        from routers.homeworks_import import commit_batch
        _seed_batch(fake_db, state="paused")
        for i in range(2):
            _seed_staging(fake_db, f"sc-{i}", "customers", "new",
                           {"first_name": f"New{i}",
                            "email": f"new{i}@x.com"})
        r = await commit_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["ok"] is True
        assert r["state"] == "committed"
        assert r["entity_counts_completed"]["customers"] == 2
        assert r["error_count"] == 0
        # Both customers landed with import_batch_id set.
        cust_docs = fake_db["customers"].docs
        assert len(cust_docs) == 2
        assert all(c["import_batch_id"] == "b1" for c in cust_docs)
        assert {c["email"] for c in cust_docs} == {
            "new0@x.com", "new1@x.com"}
        # Staging rows are stamped with imported_at → resume is a no-op.
        assert all(s["imported_at"] is not None
                    for s in fake_db["staging"].docs)
        # Batch flipped to committed with completed_at set.
        b = fake_db["batches"].docs[0]
        assert b["state"] == "committed"
        assert b["completed_at"]
        assert b["started_at"]

    asyncio.run(_run())


def test_commit_matched_merge_preserves_existing_customer_name(fake_db):
    async def _run():
        from routers.homeworks_import import commit_batch
        _seed_batch(fake_db, state="paused")
        # Existing customer already has a first_name — matched merge
        # must NOT overwrite it, but MUST extend tags and append notes.
        fake_db["customers"].docs.append({
            "id": "c-existing", "tenant_id": "tenant-A",
            "first_name": "Original", "last_name": "Owner",
            "email": "existing@x.com",
            "tags": ["VIP"], "notes": "House rules apply.",
        })
        _seed_staging(fake_db, "sc-mat", "customers", "matched", {
            "first_name": "OVERWRITTEN",    # must be ignored (protected)
            "last_name": "ALSO_IGNORED",    # protected
            "phone": "555-1212",            # protected AND blank on existing → filled
            "tags": ["Imported"],           # merge with VIP
            "notes": "Homeworks: pref am.",  # append to existing
            "pool_gallons": 15000,          # non-protected → set
        }, matched_target_id="c-existing")

        r = await commit_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["ok"] is True
        merged = fake_db["customers"].docs[0]
        # Protected fields preserved.
        assert merged["first_name"] == "Original"
        assert merged["last_name"] == "Owner"
        # Blank protected field got filled.
        assert merged["phone"] == "555-1212"
        # Tags merged (dedup + sort).
        assert set(merged["tags"]) == {"VIP", "Imported"}
        # Notes appended (contains both).
        assert "House rules apply." in merged["notes"]
        assert "Homeworks: pref am." in merged["notes"]
        # Non-protected field set from mapped payload.
        assert merged["pool_gallons"] == 15000
        # import_batch_id stamped for rollback.
        assert merged["import_batch_id"] == "b1"

    asyncio.run(_run())


def test_commit_conflict_row_is_skipped_and_records_commit_error(fake_db):
    async def _run():
        from routers.homeworks_import import commit_batch
        _seed_batch(fake_db, state="paused")
        _seed_staging(fake_db, "sc-conf", "customers", "conflict",
                       {"first_name": "Dupe"})
        _seed_staging(fake_db, "sc-ok", "customers", "new",
                       {"first_name": "Ok"})
        r = await commit_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["ok"] is True
        # Only the "new" row landed as a customer doc.
        assert len(fake_db["customers"].docs) == 1
        assert fake_db["customers"].docs[0]["first_name"] == "Ok"
        # Both staging rows are marked imported_at (conflict is an
        # INTENTIONAL skip — Resume must not re-process it).
        conflict_row = next(s for s in fake_db["staging"].docs
                             if s["id"] == "sc-conf")
        ok_row = next(s for s in fake_db["staging"].docs
                       if s["id"] == "sc-ok")
        assert conflict_row["imported_at"] is not None
        assert conflict_row["commit_error"] == "conflict_skipped"
        assert ok_row["imported_at"] is not None
        assert ok_row["commit_error"] is None
        # error_count reflects only UNEXPECTED errors (0 here).
        assert r["error_count"] == 0

    asyncio.run(_run())


def test_rollback_from_committed_state_purges_everything(fake_db):
    async def _run():
        from routers.homeworks_import import (commit_batch,
                                                 rollback_batch)
        _seed_batch(fake_db, state="paused")
        for i in range(3):
            _seed_staging(fake_db, f"sc-{i}", "customers", "new",
                           {"first_name": f"C{i}"})
        # Commit → 3 customers inserted, batch → committed.
        await commit_batch("b1", user=ADMIN, tenant=TENANT)
        assert len(fake_db["customers"].docs) == 3
        assert fake_db["batches"].docs[0]["state"] == "committed"
        # Rollback from committed → purges the 3 customers AND flips
        # state to rolled_back.
        r = await rollback_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["ok"] is True
        assert r["purged_counts"]["customers"] == 3
        # The staging rows are also purged (audit — no ghost rows).
        assert r["purged_counts"]["homeworks_staging"] == 3
        assert len(fake_db["customers"].docs) == 0
        assert fake_db["batches"].docs[0]["state"] == "rolled_back"

    asyncio.run(_run())


def test_progress_endpoint_returns_state_and_counts(fake_db):
    async def _run():
        from routers.homeworks_import import batch_progress
        _seed_batch(fake_db, state="paused",
                     entity_counts_completed={"customers": 42},
                     entity_counts_total={"customers": 100},
                     current_entity_type="customers",
                     error_count=1)
        r = await batch_progress("b1", user=ADMIN, tenant=TENANT)
        assert r["state"] == "paused"
        assert r["entity_counts_completed"]["customers"] == 42
        assert r["entity_counts_total"]["customers"] == 100
        assert r["current_entity_type"] == "customers"
        assert r["error_count"] == 1

    asyncio.run(_run())


def test_commit_rejected_from_pending_state(fake_db):
    async def _run():
        from fastapi import HTTPException
        from routers.homeworks_import import commit_batch
        _seed_batch(fake_db, state="pending")
        with pytest.raises(HTTPException) as ex:
            await commit_batch("b1", user=ADMIN, tenant=TENANT)
        assert ex.value.status_code == 400
        assert ex.value.detail["error"] == "not_committable"
        assert ex.value.detail["state"] == "pending"

    asyncio.run(_run())
