"""Phase 55-b · Aug-2026 — Copilot scraper + dedupe + orchestrator tests.

All Playwright interactions are mocked — no live network calls, no
Playwright runtime dependency. The scraper class is bypassed entirely
in the orchestrator tests by monkey-patching ``_run_scrape`` to
directly invoke the persistence helpers with fake rows.
"""
from __future__ import annotations

import asyncio

import pytest


# ── Shared fake collection (mirrors 55-a scaffold pattern) ──
class _DeleteResult:
    def __init__(self, n): self.deleted_count = n


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    @staticmethod
    def _match(d, q):
        for k, v in q.items():
            # Support $regex for email case-insensitive match — the
            # dedupe engine relies on it.
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
    homeworks_credentials = _FakeColl()
    for name, coll in (("import_batches", batches),
                         ("homeworks_staging", staging),
                         ("customers", customers),
                         ("properties", properties),
                         ("homeworks_credentials", homeworks_credentials)):
        monkeypatch.setattr(_real, name, coll, raising=False)
    original_getitem = type(_real).__getitem__

    def _getitem(self, name):
        override = {"import_batches": batches,
                    "homeworks_staging": staging,
                    "customers": customers,
                    "properties": properties,
                    "homeworks_credentials": homeworks_credentials}
        if name in override:
            return override[name]
        return original_getitem(self, name)
    monkeypatch.setattr(type(_real), "__getitem__", _getitem)
    return {"batches": batches, "staging": staging,
             "customers": customers, "properties": properties,
             "credentials": homeworks_credentials}


ADMIN = {"id": "u-a", "role": "admin", "tenant_id": "tenant-A"}
TENANT = {"id": "tenant-A"}


# ═══ Dedupe engine — pure ═══════════════════════════════════════
def test_dedupe_new_when_no_existing_customer(fake_db):
    async def _run():
        from services.homeworks.dedupe import dedupe_customer
        ds, tid = await dedupe_customer(
            "tenant-A", {"email": "new@x.com", "phone": "555-1212"},
            _RealDbShim(fake_db))
        assert ds == "new"
        assert tid is None
    asyncio.run(_run())


def test_dedupe_matched_by_email_case_insensitive(fake_db):
    async def _run():
        from services.homeworks.dedupe import dedupe_customer
        fake_db["customers"].docs.append({
            "id": "c-1", "tenant_id": "tenant-A",
            "email": "OldSchool@X.COM", "phone": "999-0000",
        })
        ds, tid = await dedupe_customer(
            "tenant-A", {"email": "oldschool@x.com"},
            _RealDbShim(fake_db))
        assert ds == "matched"
        assert tid == "c-1"
    asyncio.run(_run())


def test_dedupe_matched_by_phone_normalized(fake_db):
    async def _run():
        from services.homeworks.dedupe import dedupe_customer
        # Existing customer stored with punctuation + country code.
        fake_db["customers"].docs.append({
            "id": "c-2", "tenant_id": "tenant-A",
            "email": "", "phone": "+1 (555) 123-4567",
        })
        # Scraped phone uses a different format but same digits.
        ds, tid = await dedupe_customer(
            "tenant-A", {"phone": "555.123.4567"},
            _RealDbShim(fake_db))
        assert ds == "matched"
        assert tid == "c-2"
    asyncio.run(_run())


def test_dedupe_conflict_when_email_and_phone_hit_different_customers(fake_db):
    async def _run():
        from services.homeworks.dedupe import dedupe_customer
        fake_db["customers"].docs.append({
            "id": "c-email-only", "tenant_id": "tenant-A",
            "email": "conflict@x.com", "phone": "111-1111",
        })
        fake_db["customers"].docs.append({
            "id": "c-phone-only", "tenant_id": "tenant-A",
            "email": "other@x.com", "phone": "555-1212",
        })
        ds, tid = await dedupe_customer(
            "tenant-A",
            {"email": "conflict@x.com", "phone": "5551212"},
            _RealDbShim(fake_db))
        assert ds == "conflict"
        assert tid is None
    asyncio.run(_run())


# ═══ Orchestrator — persist rows via fake scraper ══════════════
async def _fake_scraper_iter_customers(page):
    for i, row in enumerate((
        {"id": "hw-c-1", "first_name": "Alice", "last_name": "Smith",
         "email": "alice@x.com", "phone": "555-0001", "tags": "VIP",
         "notes": "Weekly service", "billing_address": "1 Ash St"},
        {"id": "hw-c-2", "first_name": "Bob", "last_name": "Jones",
         "email": "match@x.com", "phone": "555-0002",
         "billing_address": "2 Birch St"},
    )):
        # Mapper is called by the scraper's real iter — mimic it.
        from services.homeworks.mapping import map_customer
        yield row, map_customer(row)


async def _fake_scraper_iter_properties(page):
    for row in (
        {"id": "hw-p-1", "customer_homeworks_id": "hw-c-1",
         "label": "Backyard pool", "address": "1 Ash St",
         "city": "Austin"},
        {"id": "hw-p-2", "customer_homeworks_id": "hw-c-2",
         "label": "Front lawn", "address": "2 Birch St",
         "city": "Austin"},
    ):
        from services.homeworks.mapping import map_property
        yield row, map_property(row)


class _FakeScraper:
    slug = "homeworks"
    session_cookies: list = []

    def __init__(self): self.session_cookies = []

    async def authenticate(self, page): return None

    def iter_customers(self, page): return _fake_scraper_iter_customers(page)
    def iter_properties(self, page): return _fake_scraper_iter_properties(page)


class _ChallengingScraper:
    slug = "homeworks"
    session_cookies: list = []

    async def authenticate(self, page):
        from services.suppliers.challenge import SupplierChallengeRequired
        raise SupplierChallengeRequired(
            "homeworks", "https://secure.copilotcrm.com/login")

    def iter_customers(self, page): raise RuntimeError("unreachable")
    def iter_properties(self, page): raise RuntimeError("unreachable")


def _seed_batch_pending(fake_db, credentials=True):
    fake_db["batches"].docs.append({
        "id": "b1", "tenant_id": "tenant-A", "state": "pending",
        "source": "copilot_crm",
        "entity_types_planned": ["customers", "properties"],
        "entity_counts": {}, "started_at": None,
    })
    if credentials:
        # Fernet-encrypted values — the router decrypts them; the
        # fixture uses ``services.suppliers.crypto`` under the hood.
        from services.suppliers.crypto import encrypt
        fake_db["credentials"].docs.append({
            "tenant_id": "tenant-A", "source": "copilot_crm",
            "encrypted_email": encrypt("admin@copilotcrm.com"),
            "encrypted_password": encrypt("hunter2"),
        })


def _patch_run_scrape_with(monkeypatch, scraper):
    """Replace ``_run_scrape`` with an in-memory driver that skips
    Playwright entirely."""
    import routers.homeworks_import as hw

    async def _fake_run(batch_id, tenant_id, s):
        # Mirror the real orchestrator body without opening a browser.
        from services.homeworks.dedupe import dedupe_customer
        await s.authenticate(page=None)
        scraped = {"customers": 0, "properties": 0}
        async for raw, mapped in s.iter_customers(None):
            await hw._persist_customer_row(
                tenant_id, batch_id, raw, mapped, dedupe_customer)
            scraped["customers"] += 1
        async for raw, mapped in s.iter_properties(None):
            await hw._persist_property_row(
                tenant_id, batch_id, raw, mapped)
            scraped["properties"] += 1
        return scraped

    async def _factory(*_a, **_kw):
        return scraper
    monkeypatch.setattr(hw, "_run_scrape", _fake_run)
    # Also patch the scraper class so the router's import doesn't
    # complain (it constructs one before calling _run_scrape).
    import services.homeworks.copilot_scraper as cs
    monkeypatch.setattr(cs, "CopilotCRMScraper",
                          lambda **kw: scraper)
    # Bypass ``get_active_session`` — it touches the real Motor client
    # which is bound to a different event loop under pytest's per-test
    # asyncio.run() driver.
    import services.suppliers.sessions as _sessions

    async def _no_session(*_a, **_kw): return []
    monkeypatch.setattr(_sessions, "get_active_session", _no_session)


def test_scrape_populates_customer_staging_with_dedupe(fake_db, monkeypatch):
    async def _run():
        from routers.homeworks_import import scrape_batch
        _seed_batch_pending(fake_db)
        # Existing customer that will trigger a MATCHED dedupe on
        # ``hw-c-2`` (email match).
        fake_db["customers"].docs.append({
            "id": "c-existing", "tenant_id": "tenant-A",
            "email": "match@x.com", "phone": "999-9999",
        })
        _patch_run_scrape_with(monkeypatch, _FakeScraper())

        r = await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["ok"] is True
        assert r["state"] == "paused"
        assert r["entity_counts_scraped"] == {
            "customers": 2, "properties": 2}
        # 4 staging rows: 2 customers + 2 properties.
        cust_stagings = [s for s in fake_db["staging"].docs
                          if s["entity_type"] == "customers"]
        prop_stagings = [s for s in fake_db["staging"].docs
                          if s["entity_type"] == "properties"]
        assert len(cust_stagings) == 2
        assert len(prop_stagings) == 2

        # hw-c-1 → new (unknown email).
        c1 = next(s for s in cust_stagings if s["homeworks_id"] == "hw-c-1")
        assert c1["dedupe_status"] == "new"
        # New rows get a pre-assigned UUID inside mapped_payload.id so
        # property staging rows can FK-resolve before commit.
        assert c1["mapped_payload"].get("id"), (
            "new rows must carry a pre-assigned mapped.id")

        # hw-c-2 → matched (email "match@x.com" hits c-existing).
        c2 = next(s for s in cust_stagings if s["homeworks_id"] == "hw-c-2")
        assert c2["dedupe_status"] == "matched"
        assert c2["matched_target_id"] == "c-existing"

        # Batch state flipped to paused with counts_total ready for
        # the dry-run endpoint.
        b = fake_db["batches"].docs[0]
        assert b["state"] == "paused"
        assert b["entity_counts_scraped"] == {
            "customers": 2, "properties": 2}
        assert b["entity_counts_total"]["customers"] == 2
        assert b["entity_counts_total"]["properties"] == 2

    asyncio.run(_run())


def test_property_staging_references_customer_via_matched_target_id(
    fake_db, monkeypatch,
):
    async def _run():
        from routers.homeworks_import import scrape_batch
        _seed_batch_pending(fake_db)
        # Force hw-c-2 to match an existing customer id.
        fake_db["customers"].docs.append({
            "id": "c-existing", "tenant_id": "tenant-A",
            "email": "match@x.com", "phone": "999-9999",
        })
        _patch_run_scrape_with(monkeypatch, _FakeScraper())

        await scrape_batch("b1", user=ADMIN, tenant=TENANT)

        prop_stagings = [s for s in fake_db["staging"].docs
                          if s["entity_type"] == "properties"]
        # hw-p-2's parent is hw-c-2 (matched to c-existing) — FK must
        # point at c-existing, NOT a scraper-invented UUID.
        p2 = next(s for s in prop_stagings if s["homeworks_id"] == "hw-p-2")
        assert p2["mapped_payload"]["customer_id"] == "c-existing"
        # hw-p-1's parent is hw-c-1 (new) — FK must be the pre-
        # assigned staging.mapped_payload.id (so commit engine can
        # cascade the insert cleanly).
        c1 = next(s for s in fake_db["staging"].docs
                   if s["entity_type"] == "customers"
                   and s["homeworks_id"] == "hw-c-1")
        p1 = next(s for s in prop_stagings if s["homeworks_id"] == "hw-p-1")
        assert p1["mapped_payload"]["customer_id"] == \
            c1["mapped_payload"]["id"]

    asyncio.run(_run())


def test_challenge_detected_transitions_batch_to_paused_challenge(
    fake_db, monkeypatch,
):
    async def _run():
        from routers.homeworks_import import scrape_batch
        _seed_batch_pending(fake_db)
        _patch_run_scrape_with(monkeypatch, _ChallengingScraper())

        r = await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["ok"] is False
        assert r["challenge_required"] is True
        assert r["slug"] == "homeworks"
        assert r["ttl_hint_minutes"] == 30
        assert r["challenge_id"]  # non-empty
        # State flipped to paused_challenge — retry-after-handoff path.
        assert fake_db["batches"].docs[0]["state"] == "paused_challenge"

    asyncio.run(_run())


def test_scrape_rejected_without_credentials(fake_db, monkeypatch):
    async def _run():
        from fastapi import HTTPException
        from routers.homeworks_import import scrape_batch
        _seed_batch_pending(fake_db, credentials=False)
        with pytest.raises(HTTPException) as ex:
            await scrape_batch("b1", user=ADMIN, tenant=TENANT)
        assert ex.value.status_code == 400
        assert ex.value.detail["error"] == "no_credentials"

    asyncio.run(_run())


# ─── helper (Mongo-shape adapter over the fake) ─────────────────
class _RealDbShim:
    """Thin wrapper so ``dedupe_customer`` can call ``db_ref.customers.find``."""
    def __init__(self, fake): self.customers = fake["customers"]
