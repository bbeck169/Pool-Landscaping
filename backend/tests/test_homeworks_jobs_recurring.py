"""Phase 55-c · Aug-2026 — Jobs + Recurring Schedule import tests.

All Playwright interactions are mocked — no live network calls. The
scraper class is replaced with an in-memory fake that yields 4 entity
types in FK-safe order (customers → properties → jobs → recurring).
"""
from __future__ import annotations

import asyncio

import pytest


# ── Shared fake collection (same shape as 55-b) ─────────────────
class _DeleteResult:
    def __init__(self, n): self.deleted_count = n


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    @staticmethod
    def _match(d, q):
        for k, v in q.items():
            if isinstance(v, dict) and "$regex" in v:
                import re as _re
                stored = d.get(k)
                if stored is None:
                    return False
                opts = v.get("$options", "")
                flags = _re.IGNORECASE if "i" in opts else 0
                if not _re.fullmatch(v["$regex"], str(stored), flags):
                    return False
                continue
            if isinstance(v, dict) and "$exists" in v:
                exists = k in d and d.get(k) is not None
                if bool(v["$exists"]) != exists:
                    return False
                continue
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
    recurring = _FakeColl()
    homeworks_credentials = _FakeColl()
    for name, coll in (("import_batches", batches),
                         ("homeworks_staging", staging),
                         ("customers", customers),
                         ("properties", properties),
                         ("jobs", jobs),
                         ("recurring_schedules", recurring),
                         ("homeworks_credentials", homeworks_credentials)):
        monkeypatch.setattr(_real, name, coll, raising=False)
    original_getitem = type(_real).__getitem__

    def _getitem(self, name):
        override = {"import_batches": batches,
                    "homeworks_staging": staging,
                    "customers": customers,
                    "properties": properties,
                    "jobs": jobs,
                    "recurring_schedules": recurring,
                    "homeworks_credentials": homeworks_credentials}
        if name in override:
            return override[name]
        return original_getitem(self, name)
    monkeypatch.setattr(type(_real), "__getitem__", _getitem)
    return {"batches": batches, "staging": staging,
             "customers": customers, "properties": properties,
             "jobs": jobs, "recurring": recurring,
             "credentials": homeworks_credentials}


ADMIN = {"id": "u-a", "role": "admin", "tenant_id": "tenant-A"}
TENANT = {"id": "tenant-A"}


# ═══ Mappers — pure ═══════════════════════════════════════════════
def test_map_job_resolves_customer_and_property_fks():
    from services.homeworks.mapping import map_job
    raw = {
        "id": "hw-j-1",
        "customer_homeworks_id": "hw-c-99",
        "property_homeworks_id": "hw-p-99",
        "title": "Weekly clean",
        "description": "Bring salt",
        "status": "Scheduled",
        "scheduled_at": "2026-09-01T10:00:00",
        "scheduled_end":   "2026-09-01T12:00:00",
        "duration_minutes": 120,
        "assigned_to_email": "tech@aquaterra.com",
        "service_template_hint": "weekly_maint",
        "notes": "Gate code 1234",
    }
    mapped = map_job(raw,
                       customer_target_id="c-99",
                       property_target_id="p-99")
    assert mapped["title"] == "Weekly clean"
    assert mapped["customer_id"] == "c-99"
    assert mapped["property_id"] == "p-99"
    assert mapped["status"] == "scheduled"    # lowered
    assert mapped["scheduled_date"] == "2026-09-01T10:00:00"
    assert mapped["duration_minutes"] == 120
    assert mapped["assigned_to_email"] == "tech@aquaterra.com"
    assert mapped["service_template_hint"] == "weekly_maint"
    assert mapped["homeworks_id"] == "hw-j-1"
    assert mapped["notes"] == "Gate code 1234"


def test_map_job_falls_back_to_description_when_no_notes():
    from services.homeworks.mapping import map_job
    raw = {"id": "hw-j-2", "title": "Setup",
           "description": "Only description field, no notes."}
    mapped = map_job(raw)
    assert mapped["notes"] == "Only description field, no notes."


def test_map_recurring_normalizes_interval_type_and_infers_days():
    from services.homeworks.mapping import map_recurring_schedule
    raw = {
        "id": "hw-r-1",
        "interval_type": "BiWeekly",   # cased, no days provided
        "next_run_at": "2026-09-05",
        "active": True,
        "service_template_hint": "pool_service",
    }
    mapped = map_recurring_schedule(
        raw, customer_target_id="c-1", property_target_id="p-1")
    assert mapped["interval_type"] == "biweekly"
    assert mapped["interval_days"] == 14
    assert mapped["customer_id"] == "c-1"
    assert mapped["property_id"] == "p-1"
    assert mapped["active"] is True
    assert mapped["homeworks_id"] == "hw-r-1"


def test_map_recurring_coerces_unknown_interval_to_custom():
    from services.homeworks.mapping import map_recurring_schedule
    mapped = map_recurring_schedule(
        {"id": "hw-r-2", "interval_type": "yearly-ish"})
    assert mapped["interval_type"] == "custom"
    # interval_days stays None when interval_type is custom + not given.
    assert "interval_days" not in mapped


# ═══ Dedupe by homeworks_id ═════════════════════════════════════
class _DbShim:
    """``db_ref[collection]`` accessor over a fake_db dict."""
    def __init__(self, fake): self._fake = fake
    def __getitem__(self, name):
        # ``recurring_schedules`` → fake_db["recurring"] key alias.
        alias = "recurring" if name == "recurring_schedules" else name
        return self._fake[alias]


def test_dedupe_by_homeworks_id_new_when_absent(fake_db):
    async def _run():
        from services.homeworks.dedupe import dedupe_by_homeworks_id
        ds, tid = await dedupe_by_homeworks_id(
            "tenant-A", "jobs", "hw-j-1", _DbShim(fake_db))
        assert ds == "new"
        assert tid is None
    asyncio.run(_run())


def test_dedupe_by_homeworks_id_matched_when_single_existing(fake_db):
    async def _run():
        from services.homeworks.dedupe import dedupe_by_homeworks_id
        fake_db["jobs"].docs.append({
            "id": "job-existing", "tenant_id": "tenant-A",
            "homeworks_id": "hw-j-1",
        })
        ds, tid = await dedupe_by_homeworks_id(
            "tenant-A", "jobs", "hw-j-1", _DbShim(fake_db))
        assert ds == "matched"
        assert tid == "job-existing"
    asyncio.run(_run())


# ═══ Orchestrator with fake scraper (4 entity types) ════════════
async def _fake_customers(page):
    from services.homeworks.mapping import map_customer
    for row in (
        {"id": "hw-c-1", "first_name": "Alice",
         "email": "a@x.com", "phone": "555-1000"},
        {"id": "hw-c-2", "first_name": "Bob",
         "email": "b@x.com", "phone": "555-2000"},
    ):
        yield row, map_customer(row)


async def _fake_properties(page):
    from services.homeworks.mapping import map_property
    for row in (
        {"id": "hw-p-1", "customer_homeworks_id": "hw-c-1",
         "label": "Backyard pool", "address": "1 Ash St"},
        {"id": "hw-p-2", "customer_homeworks_id": "hw-c-2",
         "label": "Front lawn", "address": "2 Birch St"},
    ):
        yield row, map_property(row)


async def _fake_jobs(page):
    from services.homeworks.mapping import map_job
    for row in (
        {"id": "hw-j-1",
         "customer_homeworks_id": "hw-c-1",
         "property_homeworks_id": "hw-p-1",
         "title": "Clean", "status": "scheduled",
         "scheduled_at": "2026-09-01"},
        {"id": "hw-j-2",
         "customer_homeworks_id": "hw-c-2",
         "property_homeworks_id": "hw-p-2",
         "title": "Repair", "status": "completed",
         "scheduled_at": "2026-08-15"},
        {"id": "hw-j-3",
         "customer_homeworks_id": "hw-c-1",
         "property_homeworks_id": "hw-p-1",
         "title": "Follow-up", "status": "pending",
         "scheduled_at": "2026-09-08"},
    ):
        yield row, map_job(row)


async def _fake_recurring(page):
    from services.homeworks.mapping import map_recurring_schedule
    for row in (
        {"id": "hw-r-1",
         "customer_homeworks_id": "hw-c-1",
         "property_homeworks_id": "hw-p-1",
         "interval_type": "weekly",
         "next_run_at": "2026-09-08"},
    ):
        yield row, map_recurring_schedule(row)


class _FakeScraper4:
    slug = "homeworks"
    session_cookies: list = []
    async def authenticate(self, page): return None
    def iter_customers(self, page): return _fake_customers(page)
    def iter_properties(self, page): return _fake_properties(page)
    def iter_jobs(self, page): return _fake_jobs(page)
    def iter_recurring_schedules(self, page): return _fake_recurring(page)


def _seed_batch_pending(fake_db, entity_types=None):
    fake_db["batches"].docs.append({
        "id": "b1", "tenant_id": "tenant-A", "state": "pending",
        "source": "copilot_crm",
        "entity_types_planned": entity_types or [
            "customers", "properties", "jobs", "recurring_schedules"],
        "entity_counts": {}, "started_at": None,
    })
    from services.suppliers.crypto import encrypt
    fake_db["credentials"].docs.append({
        "tenant_id": "tenant-A", "source": "copilot_crm",
        "encrypted_email": encrypt("admin@copilotcrm.com"),
        "encrypted_password": encrypt("hunter2"),
    })


def _patch_run_scrape_with(monkeypatch, scraper):
    import routers.homeworks_import as hw

    async def _fake_run(batch_id, tenant_id, s):
        from services.homeworks.dedupe import (
            dedupe_customer, dedupe_by_homeworks_id,
        )
        await s.authenticate(page=None)
        scraped = {"customers": 0, "properties": 0,
                    "jobs": 0, "recurring_schedules": 0}
        async for raw, mapped in s.iter_customers(None):
            await hw._persist_customer_row(
                tenant_id, batch_id, raw, mapped, dedupe_customer)
            scraped["customers"] += 1
        async for raw, mapped in s.iter_properties(None):
            await hw._persist_property_row(
                tenant_id, batch_id, raw, mapped)
            scraped["properties"] += 1
        async for raw, mapped in s.iter_jobs(None):
            await hw._persist_job_row(
                tenant_id, batch_id, raw, mapped, dedupe_by_homeworks_id)
            scraped["jobs"] += 1
        async for raw, mapped in s.iter_recurring_schedules(None):
            await hw._persist_recurring_row(
                tenant_id, batch_id, raw, mapped, dedupe_by_homeworks_id)
            scraped["recurring_schedules"] += 1
        return scraped

    monkeypatch.setattr(hw, "_run_scrape", _fake_run)
    import services.homeworks.copilot_scraper as cs
    monkeypatch.setattr(cs, "CopilotCRMScraper",
                          lambda **kw: scraper)
    import services.suppliers.sessions as _sessions

    async def _no_session(*_a, **_kw): return []
    monkeypatch.setattr(_sessions, "get_active_session", _no_session)


def test_scraper_orchestrator_runs_all_four_entity_types_in_order(
    fake_db, monkeypatch,
):
    async def _run():
        from routers.homeworks_import import scrape_batch
        _seed_batch_pending(fake_db)
        _patch_run_scrape_with(monkeypatch, _FakeScraper4())

        r = await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["ok"] is True
        assert r["entity_counts_scraped"] == {
            "customers": 2, "properties": 2,
            "jobs": 3, "recurring_schedules": 1,
        }
        # Verify FK resolution on jobs — every job carries a
        # customer_id + property_id that matches the SAME batch's
        # customer/property staging rows (new customers use their
        # pre-assigned mapped.id).
        cust_stagings = {
            s["homeworks_id"]: s for s in fake_db["staging"].docs
            if s["entity_type"] == "customers"}
        prop_stagings = {
            s["homeworks_id"]: s for s in fake_db["staging"].docs
            if s["entity_type"] == "properties"}
        job_stagings = [s for s in fake_db["staging"].docs
                         if s["entity_type"] == "jobs"]
        assert len(job_stagings) == 3
        for j in job_stagings:
            raw = j["raw_payload"]
            expected_cust = cust_stagings[raw["customer_homeworks_id"]] \
                ["mapped_payload"]["id"]
            expected_prop = prop_stagings[raw["property_homeworks_id"]] \
                ["mapped_payload"]["id"]
            assert j["mapped_payload"]["customer_id"] == expected_cust
            assert j["mapped_payload"]["property_id"] == expected_prop
        # Recurring FK check.
        rec_stagings = [s for s in fake_db["staging"].docs
                         if s["entity_type"] == "recurring_schedules"]
        assert len(rec_stagings) == 1
        r0 = rec_stagings[0]
        assert r0["mapped_payload"]["customer_id"] == \
            cust_stagings["hw-c-1"]["mapped_payload"]["id"]
        # Total entity counts in the batch doc.
        b = fake_db["batches"].docs[0]
        assert b["entity_counts_total"]["jobs"] == 3
        assert b["entity_counts_total"]["recurring_schedules"] == 1
        assert b["state"] == "paused"
    asyncio.run(_run())


def test_commit_engine_lands_scraped_jobs_into_jobs_collection(
    fake_db, monkeypatch,
):
    async def _run():
        from routers.homeworks_import import scrape_batch, commit_batch
        _seed_batch_pending(fake_db)
        _patch_run_scrape_with(monkeypatch, _FakeScraper4())

        await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        r = await commit_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["state"] == "committed"
        # 3 jobs staged as ``new`` — commit engine inserts them into
        # the ``jobs`` collection with ``import_batch_id`` set.
        assert len(fake_db["jobs"].docs) == 3
        assert all(j["import_batch_id"] == "b1"
                    for j in fake_db["jobs"].docs)
        # 1 recurring schedule lands too.
        assert len(fake_db["recurring"].docs) == 1
        # Progress reports capture per-entity completion.
        assert r["entity_counts_completed"]["jobs"] == 3
        assert r["entity_counts_completed"]["recurring_schedules"] == 1
    asyncio.run(_run())


def test_rollback_purges_jobs_and_recurring_alongside_customers(
    fake_db, monkeypatch,
):
    async def _run():
        from routers.homeworks_import import (
            scrape_batch, commit_batch, rollback_batch,
        )
        _seed_batch_pending(fake_db)
        _patch_run_scrape_with(monkeypatch, _FakeScraper4())

        await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        await commit_batch("b1", user=ADMIN, tenant=TENANT)
        assert len(fake_db["jobs"].docs) == 3
        assert len(fake_db["recurring"].docs) == 1
        assert len(fake_db["customers"].docs) == 2

        r = await rollback_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["ok"] is True
        # Every committed target row purged.
        assert r["purged_counts"]["customers"] == 2
        assert r["purged_counts"]["properties"] == 2
        assert r["purged_counts"]["jobs"] == 3
        assert r["purged_counts"]["recurring_schedules"] == 1
        # Batch flips to rolled_back.
        assert fake_db["batches"].docs[0]["state"] == "rolled_back"
        assert len(fake_db["jobs"].docs) == 0
        assert len(fake_db["recurring"].docs) == 0
    asyncio.run(_run())
