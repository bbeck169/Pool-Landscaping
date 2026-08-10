"""Phase 55-d · Aug-2026 — Invoices + Payments + Quotes import tests.

All Playwright interactions are mocked. The scraper class is replaced
with an in-memory fake that yields 7 entity types in FK-safe order
(customers → properties → jobs → recurring → quotes → invoices →
payments).
"""
from __future__ import annotations

import asyncio

import pytest


# ── Shared fake collection (same shape as 55-b/55-c) ─────────────
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
    invoices = _FakeColl()
    payments = _FakeColl()
    quotes = _FakeColl()
    homeworks_credentials = _FakeColl()
    for name, coll in (("import_batches", batches),
                         ("homeworks_staging", staging),
                         ("customers", customers),
                         ("properties", properties),
                         ("jobs", jobs),
                         ("recurring_schedules", recurring),
                         ("invoices", invoices),
                         ("payments", payments),
                         ("quotes", quotes),
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
                    "invoices": invoices,
                    "payments": payments,
                    "quotes": quotes,
                    "homeworks_credentials": homeworks_credentials}
        if name in override:
            return override[name]
        return original_getitem(self, name)
    monkeypatch.setattr(type(_real), "__getitem__", _getitem)
    return {"batches": batches, "staging": staging,
             "customers": customers, "properties": properties,
             "jobs": jobs, "recurring": recurring,
             "invoices": invoices, "payments": payments,
             "quotes": quotes, "credentials": homeworks_credentials}


ADMIN = {"id": "u-a", "role": "admin", "tenant_id": "tenant-A"}
TENANT = {"id": "tenant-A"}


# ═══ Mappers — pure ═══════════════════════════════════════════════
def test_map_invoice_produces_header_and_line_items():
    from services.homeworks.mapping import map_invoice
    raw = {
        "id": "hw-i-1",
        "invoice_number": "INV-2026-0042",
        "status": "SENT",
        "line_items": [
            {"id": "hw-il-1", "description": "Weekly clean",
             "quantity": 4, "unit_price": 75.0, "tax_rate": 0.0625,
             "wholesale_price_snapshot": 12.50},
            {"id": "hw-il-2", "description": "Chlorine tabs",
             "quantity": 2, "unit_price": 45.0},
            {"id": "hw-il-3", "description": "Filter",
             "quantity": 1, "unit_price": 120.0},
        ],
        "tax_rate": 0.0625,
        "subtotal_cents": 51500,
        "total_cents":    54719,
        "due_date": "2026-09-15",
    }
    mapped = map_invoice(raw, customer_target_id="c-1",
                           job_target_id="j-1")
    assert mapped["customer_id"] == "c-1"
    assert mapped["job_id"] == "j-1"
    assert mapped["invoice_number"] == "INV-2026-0042"
    assert mapped["status"] == "sent"
    assert mapped["doc_type"] == "invoice"
    assert len(mapped["line_items"]) == 3
    # Snapshots preserved verbatim.
    assert mapped["line_items"][0]["wholesale_price_snapshot"] == 12.50
    # Per-line homeworks_line_id kept for on-invoice dedupe.
    assert mapped["line_items"][0]["homeworks_line_id"] == "hw-il-1"
    assert mapped["total_cents"] == 54719


def test_map_quote_shares_line_item_shape():
    from services.homeworks.mapping import map_quote
    raw = {
        "id": "hw-q-1",
        "title": "Pool remodel estimate",
        "status": "Sent",
        "line_items": [
            {"id": "hw-ql-1", "description": "Coping stone",
             "quantity": 90, "unit_price": 18.0},
        ],
    }
    mapped = map_quote(raw, customer_target_id="c-1",
                         property_target_id="p-1")
    assert mapped["customer_id"] == "c-1"
    assert mapped["property_id"] == "p-1"
    assert mapped["doc_type"] == "quote"
    assert mapped["status"] == "sent"
    assert mapped["line_items"][0]["description"] == "Coping stone"


def test_map_payment_computes_amount_cents_when_only_dollars_provided():
    from services.homeworks.mapping import map_payment
    mapped = map_payment(
        {"id": "hw-p-1", "amount": 250.50, "method": "CARD",
         "applied_at": "2026-09-10", "transaction_ref": "ch_123",
         "stripe_charge_id": "ch_1MEEz2LkdIwHu7ix"},
        invoice_target_id="inv-1", customer_target_id="c-1",
    )
    assert mapped["invoice_id"] == "inv-1"
    assert mapped["customer_id"] == "c-1"
    assert mapped["amount_cents"] == 25050
    assert mapped["method"] == "card"
    # Stripe passthrough preserved.
    assert mapped["stripe_charge_id"] == "ch_1MEEz2LkdIwHu7ix"


# ═══ Orchestrator with fake scraper (7 entity types) ═══════════
async def _fake_customers(page):
    from services.homeworks.mapping import map_customer
    for row in (
        {"id": "hw-c-1", "first_name": "Alice",
         "email": "a@x.com", "phone": "555-1000"},
    ):
        yield row, map_customer(row)


async def _fake_properties(page):
    from services.homeworks.mapping import map_property
    for row in (
        {"id": "hw-p-1", "customer_homeworks_id": "hw-c-1",
         "label": "Home", "address": "1 Ash St"},
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
    ):
        yield row, map_job(row)


async def _fake_recurring(page):
    async def _empty():
        if False:                                                  # pragma: no cover
            yield None
    async for r in _empty():
        yield r


async def _fake_quotes(page):
    from services.homeworks.mapping import map_quote
    for row in (
        {"id": "hw-q-1",
         "customer_homeworks_id": "hw-c-1",
         "property_homeworks_id": "hw-p-1",
         "title": "Setup quote", "status": "draft",
         "line_items": [
             {"id": "hw-ql-1", "description": "Site prep",
              "quantity": 1, "unit_price": 300.0}]},
    ):
        yield row, map_quote(row)


async def _fake_invoices(page):
    from services.homeworks.mapping import map_invoice
    for row in (
        {"id": "hw-i-1", "invoice_number": "INV-A",
         "status": "sent",
         "customer_homeworks_id": "hw-c-1",
         "job_homeworks_id": "hw-j-1",
         "line_items": [
             {"id": "hw-il-1", "description": "Clean",
              "quantity": 4, "unit_price": 75.0},
             {"id": "hw-il-2", "description": "Chlorine",
              "quantity": 2, "unit_price": 45.0},
             {"id": "hw-il-3", "description": "Filter",
              "quantity": 1, "unit_price": 120.0}],
         "total_cents": 54719},
        {"id": "hw-i-2", "invoice_number": "INV-B",
         "status": "paid",
         "customer_homeworks_id": "hw-c-1",
         "job_homeworks_id": "hw-j-1",
         "line_items": [
             {"id": "hw-il-4", "description": "Repair",
              "quantity": 1, "unit_price": 200.0},
             {"id": "hw-il-5", "description": "Diagnostic",
              "quantity": 1, "unit_price": 75.0},
             {"id": "hw-il-6", "description": "Travel",
              "quantity": 1, "unit_price": 25.0}],
         "total_cents": 30000},
    ):
        yield row, map_invoice(row)


async def _fake_payments(page):
    from services.homeworks.mapping import map_payment
    for row in (
        {"id": "hw-pay-1", "invoice_homeworks_id": "hw-i-2",
         "amount": 300.00, "method": "card",
         "applied_at": "2026-09-10",
         "stripe_charge_id": "ch_alpha"},
        {"id": "hw-pay-2", "invoice_homeworks_id": "hw-i-1",
         "amount": 200.00, "method": "check",
         "applied_at": "2026-09-15"},
        {"id": "hw-pay-3", "invoice_homeworks_id": "hw-i-1",
         "amount": 347.19, "method": "card",
         "applied_at": "2026-09-20"},
    ):
        yield row, map_payment(row)


class _FakeScraper7:
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


def _seed_batch_pending(fake_db):
    fake_db["batches"].docs.append({
        "id": "b1", "tenant_id": "tenant-A", "state": "pending",
        "source": "copilot_crm",
        "entity_types_planned": [
            "customers", "properties", "jobs", "recurring_schedules",
            "quotes", "invoices", "payments"],
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
                    "jobs": 0, "recurring_schedules": 0,
                    "quotes": 0, "invoices": 0, "payments": 0}
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
        return scraped

    monkeypatch.setattr(hw, "_run_scrape", _fake_run)
    import services.homeworks.copilot_scraper as cs
    monkeypatch.setattr(cs, "CopilotCRMScraper",
                          lambda **kw: scraper)
    import services.suppliers.sessions as _sessions

    async def _no_session(*_a, **_kw): return []
    monkeypatch.setattr(_sessions, "get_active_session", _no_session)


def test_scraper_orchestrator_runs_all_seven_entity_types(
    fake_db, monkeypatch,
):
    async def _run():
        from routers.homeworks_import import scrape_batch
        _seed_batch_pending(fake_db)
        _patch_run_scrape_with(monkeypatch, _FakeScraper7())

        r = await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["ok"] is True
        assert r["entity_counts_scraped"] == {
            "customers": 1, "properties": 1,
            "jobs": 1, "recurring_schedules": 0,
            "quotes": 1, "invoices": 2, "payments": 3,
        }
        # FK sanity — every payment references one of the two staged
        # invoices via its pre-assigned mapped.id.
        inv_stagings = {
            s["homeworks_id"]: s for s in fake_db["staging"].docs
            if s["entity_type"] == "invoices"}
        pay_stagings = [s for s in fake_db["staging"].docs
                         if s["entity_type"] == "payments"]
        assert len(pay_stagings) == 3
        for p in pay_stagings:
            hw_inv = p["raw_payload"]["invoice_homeworks_id"]
            expected_inv = inv_stagings[hw_inv]["mapped_payload"]["id"]
            assert p["mapped_payload"]["invoice_id"] == expected_inv
        # Invoice→job FK resolution.
        job_id = next(
            s["mapped_payload"]["id"] for s in fake_db["staging"].docs
            if s["entity_type"] == "jobs" and s["homeworks_id"] == "hw-j-1")
        for inv in inv_stagings.values():
            assert inv["mapped_payload"]["job_id"] == job_id
        # Quote→property FK resolution.
        q = next(s for s in fake_db["staging"].docs
                  if s["entity_type"] == "quotes")
        prop_id = next(
            s["mapped_payload"]["id"] for s in fake_db["staging"].docs
            if s["entity_type"] == "properties")
        assert q["mapped_payload"]["property_id"] == prop_id
    asyncio.run(_run())


def test_commit_lands_invoices_with_line_items_and_import_batch_id(
    fake_db, monkeypatch,
):
    async def _run():
        from routers.homeworks_import import scrape_batch, commit_batch
        _seed_batch_pending(fake_db)
        _patch_run_scrape_with(monkeypatch, _FakeScraper7())

        await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        r = await commit_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["state"] == "committed"
        # 2 invoices with 3 line items each landed.
        assert len(fake_db["invoices"].docs) == 2
        for inv in fake_db["invoices"].docs:
            assert inv["import_batch_id"] == "b1"
            assert len(inv["line_items"]) == 3
        # 1 quote landed.
        assert len(fake_db["quotes"].docs) == 1
        # Progress counts.
        assert r["entity_counts_completed"]["invoices"] == 2
        assert r["entity_counts_completed"]["quotes"] == 1
    asyncio.run(_run())


def test_commit_lands_payments_with_resolved_invoice_fk(
    fake_db, monkeypatch,
):
    async def _run():
        from routers.homeworks_import import scrape_batch, commit_batch
        _seed_batch_pending(fake_db)
        _patch_run_scrape_with(monkeypatch, _FakeScraper7())

        await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        await commit_batch("b1", user=ADMIN, tenant=TENANT)

        # 3 payments landed in the payments collection.
        assert len(fake_db["payments"].docs) == 3
        # Every payment's invoice_id resolves to one of the 2 landed
        # invoices — no orphaned payments.
        invoice_ids = {i["id"] for i in fake_db["invoices"].docs}
        for p in fake_db["payments"].docs:
            assert p["import_batch_id"] == "b1"
            assert p["invoice_id"] in invoice_ids
        # Stripe charge id preserved on the first payment.
        stripe_payment = next(
            p for p in fake_db["payments"].docs
            if p.get("stripe_charge_id") == "ch_alpha")
        assert stripe_payment["amount_cents"] == 30000
    asyncio.run(_run())


def test_commit_skips_matched_invoice_without_double_line_items(fake_db):
    """Matched invoices go through the insert-only guard — the
    existing invoice's line_items are untouched and no duplicate
    append happens on the target row."""
    async def _run():
        from routers.homeworks_import import commit_batch
        # Seed: batch in "paused" with an existing invoice + 1
        # matched staging row pointing at it. If the guard fails,
        # the existing invoice's line_items subarray will get
        # overwritten OR extended.
        fake_db["batches"].docs.append({
            "id": "b1", "tenant_id": "tenant-A", "state": "paused",
            "source": "copilot_crm",
            "entity_types_planned": ["invoices"],
            "entity_counts": {}, "started_at": None,
        })
        fake_db["invoices"].docs.append({
            "id": "inv-existing", "tenant_id": "tenant-A",
            "invoice_number": "INV-A",
            "line_items": [
                {"description": "Preserved line",
                 "quantity": 1, "unit_price": 42.0}],
        })
        fake_db["staging"].docs.append({
            "id": "s-inv-1", "tenant_id": "tenant-A", "batch_id": "b1",
            "entity_type": "invoices", "homeworks_id": "hw-i-1",
            "raw_payload": {}, "mapped_payload": {
                "invoice_number": "INV-A",
                "line_items": [
                    {"description": "New line 1", "quantity": 1,
                     "unit_price": 10.0},
                    {"description": "New line 2", "quantity": 2,
                     "unit_price": 20.0},
                ],
            },
            "dedupe_status": "matched",
            "matched_target_id": "inv-existing",
            "imported_at": None, "commit_error": None,
        })

        r = await commit_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["state"] == "committed"
        # The target invoice's line_items array is UNTOUCHED.
        existing = fake_db["invoices"].docs[0]
        assert len(existing["line_items"]) == 1
        assert existing["line_items"][0]["description"] == "Preserved line"
        # Staging row stamped as an intentional skip.
        stg = fake_db["staging"].docs[0]
        assert stg["imported_at"] is not None
        assert stg["commit_error"] == \
            "matched_invoice_or_quote_skipped_insert_only"
    asyncio.run(_run())
