"""Phase 55-e · Aug-2026 — Photo + Note attachment import tests.

Object storage is monkey-patched to an in-memory store. The photo
downloader is also patched — no live HTTP anywhere. All 8 entity
types run through the orchestrator in FK-safe order.
"""
from __future__ import annotations

import asyncio

import pytest


# ── Shared fake collection (same shape as 55-d) ─────────────────
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
    colls = {name: _FakeColl() for name in (
        "import_batches", "homeworks_staging",
        "customers", "properties", "jobs",
        "recurring_schedules", "invoices", "payments",
        "quotes", "customer_notes", "job_notes",
        "homeworks_photos", "homeworks_credentials",
    )}
    for name, coll in colls.items():
        monkeypatch.setattr(_real, name, coll, raising=False)
    original_getitem = type(_real).__getitem__

    def _getitem(self, name):
        if name in colls:
            return colls[name]
        return original_getitem(self, name)
    monkeypatch.setattr(type(_real), "__getitem__", _getitem)
    return colls


@pytest.fixture
def fake_storage(monkeypatch):
    """In-memory object-storage stand-in. Records puts + deletes so
    tests can assert on both."""
    store: dict = {}
    puts: list = []
    deletes: list = []
    import services.object_storage as os_mod

    def _put(path, data, content_type):
        store[path] = (data, content_type)
        puts.append(path)
        return {"path": path, "size": len(data)}

    def _delete(path):
        deletes.append(path)
        store.pop(path, None)
        return True

    monkeypatch.setattr(os_mod, "put_object", _put)
    monkeypatch.setattr(os_mod, "delete_object", _delete)
    # Also patch the same names re-imported by the router.
    import routers.homeworks_import as hw_mod
    # The router imports these inside functions — patching the module
    # is enough because import happens on every call.
    _ = hw_mod
    return {"store": store, "puts": puts, "deletes": deletes}


ADMIN = {"id": "u-a", "role": "admin", "tenant_id": "tenant-A"}
TENANT = {"id": "tenant-A"}


# ═══ Mappers — pure ═══════════════════════════════════════════════
def test_map_note_routes_customer_vs_job_parent():
    from services.homeworks.mapping import (
        map_note, collection_for_note_parent,
    )
    assert collection_for_note_parent("customer") == "customer_notes"
    assert collection_for_note_parent("job") == "job_notes"
    n1 = map_note({"id": "n1", "text": "Hello", "created_at": "2026-08-01"},
                    "customer", "c-1")
    assert n1["parent_type"] == "customer"
    assert n1["customer_id"] == "c-1"
    assert "job_id" not in n1
    n2 = map_note({"id": "n2", "text": "Fixed pump"}, "job", "j-1")
    assert n2["parent_type"] == "job"
    assert n2["job_id"] == "j-1"
    assert "customer_id" not in n2


def test_map_photo_with_storage_url():
    from services.homeworks.mapping import map_photo
    p = map_photo(
        {"id": "ph1", "url": "https://cdn/x.jpg", "caption": "Post-clean",
         "mime_type": "image/jpeg", "size_bytes": 12345},
        "job", "j-1",
        storage_url="homeworks_import/tenant-A/b1/photos/ph1.jpeg",
    )
    assert p["parent_type"] == "job"
    assert p["parent_id"] == "j-1"
    assert p["storage_url"] == \
        "homeworks_import/tenant-A/b1/photos/ph1.jpeg"
    assert p["original_url"] == "https://cdn/x.jpg"


# ═══ Orchestrator with all 8 entity types ═══════════════════════
async def _fake_customers(page):
    from services.homeworks.mapping import map_customer
    for row in ({"id": "hw-c-1", "first_name": "Alice",
                  "email": "a@x.com", "phone": "555-1000"},
                 {"id": "hw-c-2", "first_name": "Bob",
                  "email": "b@x.com", "phone": "555-2000"}):
        yield row, map_customer(row)


async def _fake_properties(page):
    from services.homeworks.mapping import map_property
    for row in ({"id": "hw-p-1", "customer_homeworks_id": "hw-c-1",
                  "label": "Home", "address": "1 Ash St"},
                 {"id": "hw-p-2", "customer_homeworks_id": "hw-c-2",
                  "label": "Home", "address": "2 Birch St"}):
        yield row, map_property(row)


async def _fake_jobs(page):
    from services.homeworks.mapping import map_job
    for row in ({"id": "hw-j-1",
                  "customer_homeworks_id": "hw-c-1",
                  "property_homeworks_id": "hw-p-1",
                  "title": "Clean", "status": "scheduled",
                  "scheduled_at": "2026-09-01"},
                 {"id": "hw-j-2",
                  "customer_homeworks_id": "hw-c-2",
                  "property_homeworks_id": "hw-p-2",
                  "title": "Repair", "status": "completed",
                  "scheduled_at": "2026-08-15"}):
        yield row, map_job(row)


async def _fake_recurring(page):
    from services.homeworks.mapping import map_recurring_schedule
    for row in ({"id": "hw-r-1",
                  "customer_homeworks_id": "hw-c-1",
                  "property_homeworks_id": "hw-p-1",
                  "interval_type": "weekly"},):
        yield row, map_recurring_schedule(row)


async def _fake_quotes(page):
    from services.homeworks.mapping import map_quote
    for row in ({"id": "hw-q-1",
                  "customer_homeworks_id": "hw-c-1",
                  "property_homeworks_id": "hw-p-1",
                  "title": "Setup", "status": "draft",
                  "line_items": [{"description": "X",
                                     "quantity": 1, "unit_price": 100.0}]},):
        yield row, map_quote(row)


async def _fake_invoices(page):
    from services.homeworks.mapping import map_invoice
    for row in ({"id": "hw-i-1", "invoice_number": "INV-A",
                  "status": "sent",
                  "customer_homeworks_id": "hw-c-1",
                  "job_homeworks_id": "hw-j-1",
                  "line_items": [
                      {"description": "Clean", "quantity": 4,
                        "unit_price": 75.0}],
                  "total_cents": 30000},):
        yield row, map_invoice(row)


async def _fake_payments(page):
    from services.homeworks.mapping import map_payment
    for row in ({"id": "hw-pay-1", "invoice_homeworks_id": "hw-i-1",
                  "amount": 300.00, "method": "card"},):
        yield row, map_payment(row)


async def _fake_notes(page):
    from services.homeworks.mapping import map_note
    for row in ({"id": "hw-n-1", "parent_type": "customer",
                  "customer_homeworks_id": "hw-c-1",
                  "text": "Prefers am appointments"},
                 {"id": "hw-n-2", "parent_type": "job",
                  "job_homeworks_id": "hw-j-1",
                  "text": "Filter replaced"}):
        yield row, map_note(row, row["parent_type"], None)


async def _fake_attachments(page):
    from services.homeworks.mapping import map_photo
    for row in (
        {"id": "ph-1", "parent_type": "job",
         "job_homeworks_id": "hw-j-1",
         "url": "https://cdn.copilot/ph1.jpg",
         "caption": "Before", "mime_type": "image/jpeg",
         "size_bytes": 12345},
        {"id": "ph-2", "parent_type": "job",
         "job_homeworks_id": "hw-j-1",
         "url": "https://cdn.copilot/ph2.jpg",
         "caption": "After", "mime_type": "image/jpeg"},
        {"id": "ph-3", "parent_type": "customer",
         "customer_homeworks_id": "hw-c-2",
         "url": "https://cdn.copilot/ph3.png",
         "caption": "Property overview", "mime_type": "image/png"},
    ):
        yield row, map_photo(row, row["parent_type"], None, storage_url=None)


class _FakeScraper8:
    slug = "homeworks"
    session_cookies: list = []
    async def authenticate(self, page): return None
    def iter_customers(self, page): return _fake_customers(page)
    def iter_properties(self, page): return _fake_properties(page)
    def iter_jobs(self, page): return _fake_jobs(page)
    def iter_recurring_schedules(self, page): return _fake_recurring(page)
    def iter_quotes(self, page): return _fake_quotes(page)
    def iter_invoices(self, page): return _fake_invoices(page)
    def iter_payments(self, page): return _fake_payments(page)
    def iter_notes(self, page): return _fake_notes(page)
    def iter_attachments(self, page): return _fake_attachments(page)


def _seed_batch_pending(fake_db):
    fake_db["import_batches"].docs.append({
        "id": "b1", "tenant_id": "tenant-A", "state": "pending",
        "source": "copilot_crm",
        "entity_types_planned": [
            "customers", "properties", "jobs", "recurring_schedules",
            "quotes", "invoices", "payments", "attachments"],
        "entity_counts": {}, "started_at": None,
    })
    from services.suppliers.crypto import encrypt
    fake_db["homeworks_credentials"].docs.append({
        "tenant_id": "tenant-A", "source": "copilot_crm",
        "encrypted_email": encrypt("admin@copilotcrm.com"),
        "encrypted_password": encrypt("hunter2"),
    })


def _patch_run_scrape_with(monkeypatch, scraper, downloader=None):
    import routers.homeworks_import as hw

    async def _fake_run(batch_id, tenant_id, s):
        from services.homeworks.dedupe import (
            dedupe_customer, dedupe_by_homeworks_id,
        )
        await s.authenticate(page=None)
        scraped = {"customers": 0, "properties": 0,
                    "jobs": 0, "recurring_schedules": 0,
                    "quotes": 0, "invoices": 0, "payments": 0,
                    "notes": 0, "attachments": 0}
        async for raw, mapped in s.iter_customers(None):
            await hw._persist_customer_row(
                tenant_id, batch_id, raw, mapped, dedupe_customer)
            scraped["customers"] += 1
        async for raw, mapped in s.iter_properties(None):
            await hw._persist_property_row(tenant_id, batch_id, raw, mapped)
            scraped["properties"] += 1
        async for raw, mapped in s.iter_jobs(None):
            await hw._persist_job_row(
                tenant_id, batch_id, raw, mapped, dedupe_by_homeworks_id)
            scraped["jobs"] += 1
        async for raw, mapped in s.iter_recurring_schedules(None):
            await hw._persist_recurring_row(
                tenant_id, batch_id, raw, mapped, dedupe_by_homeworks_id)
            scraped["recurring_schedules"] += 1
        async for raw, mapped in s.iter_quotes(None):
            await hw._persist_quote_row(
                tenant_id, batch_id, raw, mapped, dedupe_by_homeworks_id)
            scraped["quotes"] += 1
        async for raw, mapped in s.iter_invoices(None):
            await hw._persist_invoice_row(
                tenant_id, batch_id, raw, mapped, dedupe_by_homeworks_id)
            scraped["invoices"] += 1
        async for raw, mapped in s.iter_payments(None):
            await hw._persist_payment_row(
                tenant_id, batch_id, raw, mapped, dedupe_by_homeworks_id)
            scraped["payments"] += 1
        async for raw, mapped in s.iter_notes(None):
            await hw._persist_note_row(
                tenant_id, batch_id, raw, mapped, dedupe_by_homeworks_id)
            scraped["notes"] += 1
        async for raw, mapped in s.iter_attachments(None):
            await hw._persist_attachment_row(
                tenant_id, batch_id, raw, mapped, dedupe_by_homeworks_id)
            scraped["attachments"] += 1
        return scraped

    monkeypatch.setattr(hw, "_run_scrape", _fake_run)
    import services.homeworks.copilot_scraper as cs
    monkeypatch.setattr(cs, "CopilotCRMScraper", lambda **kw: scraper)
    import services.suppliers.sessions as _sessions

    async def _no_session(*_a, **_kw): return []
    monkeypatch.setattr(_sessions, "get_active_session", _no_session)
    if downloader is not None:
        monkeypatch.setattr(cs, "download_photo", downloader)


def _happy_downloader(url):
    """Every URL → 1 KB of fake JPEG bytes."""
    return b"\xff\xd8\xff" + b"A" * 1000, "image/jpeg"


def test_scraper_orchestrator_covers_all_eight_entity_types(
    fake_db, fake_storage, monkeypatch,
):
    async def _run():
        from routers.homeworks_import import scrape_batch
        _seed_batch_pending(fake_db)
        _patch_run_scrape_with(monkeypatch, _FakeScraper8(),
                                 downloader=_happy_downloader)

        r = await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["ok"] is True
        assert r["entity_counts_scraped"] == {
            "customers": 2, "properties": 2,
            "jobs": 2, "recurring_schedules": 1,
            "quotes": 1, "invoices": 1, "payments": 1,
            "notes": 2, "attachments": 3,
        }
        # Photo blobs uploaded to storage.
        assert len(fake_storage["puts"]) == 3
        assert all(p.startswith("homeworks_import/tenant-A/b1/photos/")
                    for p in fake_storage["puts"])
        # Staging rows for notes route to customer_notes vs job_notes.
        note_types = [s["entity_type"] for s in
                       fake_db["homeworks_staging"].docs
                       if s["entity_type"].endswith("_notes")]
        assert set(note_types) == {"customer_notes", "job_notes"}
    asyncio.run(_run())


def test_photo_download_failure_persists_row_with_commit_error(
    fake_db, fake_storage, monkeypatch,
):
    """When ``download_photo`` raises (HTTP 500, DNS failure, etc.)
    the row STILL commits — just with ``storage_url=None`` and
    ``commit_error="photo_download_failed"`` so the operator can
    triage via the dry-run warnings pane."""
    async def _run():
        from routers.homeworks_import import scrape_batch
        _seed_batch_pending(fake_db)

        def _bad_downloader(url):
            raise RuntimeError("photo_download_failed: HTTP 500")

        _patch_run_scrape_with(monkeypatch, _FakeScraper8(),
                                 downloader=_bad_downloader)
        await scrape_batch("b1", user=ADMIN, tenant=TENANT)

        photo_stagings = [s for s in fake_db["homeworks_staging"].docs
                           if s["entity_type"] == "photos"]
        assert len(photo_stagings) == 3
        for p in photo_stagings:
            assert p["storage_url"] is None
            assert p["commit_error"] == "photo_download_failed"
        # No blobs uploaded (download never succeeded).
        assert fake_storage["puts"] == []
    asyncio.run(_run())


def test_photo_too_large_rejected_with_photo_too_large_marker(
    fake_db, fake_storage, monkeypatch,
):
    async def _run():
        from routers.homeworks_import import scrape_batch
        _seed_batch_pending(fake_db)

        def _huge_downloader(url):
            raise ValueError("photo_too_large")

        _patch_run_scrape_with(monkeypatch, _FakeScraper8(),
                                 downloader=_huge_downloader)
        await scrape_batch("b1", user=ADMIN, tenant=TENANT)

        photo_stagings = [s for s in fake_db["homeworks_staging"].docs
                           if s["entity_type"] == "photos"]
        for p in photo_stagings:
            assert p["storage_url"] is None
            assert p["commit_error"] == "photo_too_large"
        assert fake_storage["puts"] == []
    asyncio.run(_run())


def test_rollback_purges_storage_blobs_under_batch_prefix(
    fake_db, fake_storage, monkeypatch,
):
    """After a full scrape + commit, rollback iterates every photo
    staging row and calls ``delete_object`` on its storage_url."""
    async def _run():
        from routers.homeworks_import import (
            scrape_batch, commit_batch, rollback_batch,
        )
        _seed_batch_pending(fake_db)
        _patch_run_scrape_with(monkeypatch, _FakeScraper8(),
                                 downloader=_happy_downloader)

        await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        await commit_batch("b1", user=ADMIN, tenant=TENANT)

        # 3 blobs uploaded during scrape.
        uploaded = list(fake_storage["puts"])
        assert len(uploaded) == 3

        r = await rollback_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["ok"] is True
        # Every uploaded blob was deleted.
        assert sorted(fake_storage["deletes"]) == sorted(uploaded)
        assert r["storage_purged"] == 3
        assert r["storage_failed"] == 0
        # Photos collection purged too.
        assert r["purged_counts"]["homeworks_photos"] == 3
    asyncio.run(_run())


def test_full_eight_entity_commit_and_rollback_end_to_end(
    fake_db, fake_storage, monkeypatch,
):
    """The Phase 55 closer: 2 customers + 2 properties + 2 jobs + 1
    recurring + 1 quote + 1 invoice + 1 payment + 2 notes + 3 photos
    scrape → commit → verify all land → rollback → verify all
    (DB + storage) purged."""
    async def _run():
        from routers.homeworks_import import (
            scrape_batch, commit_batch, rollback_batch,
        )
        _seed_batch_pending(fake_db)
        _patch_run_scrape_with(monkeypatch, _FakeScraper8(),
                                 downloader=_happy_downloader)

        await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        r = await commit_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["state"] == "committed"

        assert len(fake_db["customers"].docs) == 2
        assert len(fake_db["properties"].docs) == 2
        assert len(fake_db["jobs"].docs) == 2
        assert len(fake_db["recurring_schedules"].docs) == 1
        assert len(fake_db["quotes"].docs) == 1
        assert len(fake_db["invoices"].docs) == 1
        assert len(fake_db["payments"].docs) == 1
        # Notes route to customer_notes (1) + job_notes (1).
        assert len(fake_db["customer_notes"].docs) == 1
        assert len(fake_db["job_notes"].docs) == 1
        # Photos land in the dedicated Homeworks-owned collection.
        assert len(fake_db["homeworks_photos"].docs) == 3
        for p in fake_db["homeworks_photos"].docs:
            assert p["import_batch_id"] == "b1"
            assert p["storage_url"].startswith(
                "homeworks_import/tenant-A/b1/photos/")

        # Rollback everything.
        rb = await rollback_batch("b1", user=ADMIN, tenant=TENANT)
        assert rb["ok"] is True
        for coll_name in ("customers", "properties", "jobs",
                            "recurring_schedules", "quotes",
                            "invoices", "payments",
                            "customer_notes", "job_notes",
                            "homeworks_photos"):
            assert len(fake_db[coll_name].docs) == 0, \
                f"{coll_name} not purged"
        assert rb["storage_purged"] == 3
    asyncio.run(_run())
