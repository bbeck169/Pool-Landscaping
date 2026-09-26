"""QV-service · Feb-2026 — Quote view tracker tests.

Coverage matrix (per QV-service dispatch):

  1  Happy path: denorm fields + event doc land.
  2  Event doc carries ``ua_class`` populated correctly.
  3  Auto-transition: ``sent`` → ``viewed`` + audit_logs row.
  4  Auto-transition guard: ``draft`` stays ``draft``, no audit.
  5  Auto-transition guard: ``accepted`` stays ``accepted``, no audit.
  6  Auto-transition guard: ``viewed`` stays ``viewed``, no audit
     (idempotent — a re-view on an already-viewed quote never
     re-inserts an audit row).
  7  Race safety: two concurrent views on a ``sent`` quote → both
     stamp denorm counts, EXACTLY ONE audit row is written (CAS on
     ``status: "sent"`` in the filter).
  8  Empty ``quote_id`` / ``tenant_id`` → silent no-op.
  9  Tracker never raises on DB error.
 10  30-second dedupe: two views same (quote_id, source) within
     30 s → 1 event, 1 view_count increment.
 11  Cross-tenant: tenant B's tracker call on tenant A's quote →
     no modification (tenant guard in filter).
"""
from __future__ import annotations

import asyncio
import uuid

from tests._f7_loop_fixture import run_test


def _mk_ids():
    tid = "TEST_qv_tenant_" + uuid.uuid4().hex[:10]
    qid = "TEST_qv_quote_" + uuid.uuid4().hex[:10]
    return tid, qid


async def _clean(db, tid: str, qid: str) -> None:
    await db.quotes.delete_many({"tenant_id": tid})
    await db.quote_views.delete_many({"tenant_id": tid})
    await db.audit_logs.delete_many(
        {"tenant_id": tid, "quote_id": qid},
    )


async def _seed_quote(db, tid: str, qid: str, status: str = "sent") -> None:
    """Insert a minimal quote doc so the denorm ``update_one`` +
    the atomic status CAS have a row to land on."""
    await db.quotes.insert_one({
        "id": qid,
        "tenant_id": tid,
        "doc_type": "quote",
        "status": status,
        "title": "QV test quote",
    })


# ─── 1 · Happy path — denorm fields + event doc land ───────────
def test_record_quote_view_stamps_denorm_and_event():
    from services.quote_view_tracker import record_quote_view

    async def _go(db):
        tid, qid = _mk_ids()
        await _clean(db, tid, qid)
        try:
            await _seed_quote(db, tid, qid, status="sent")
            await record_quote_view(
                quote_id=qid, tenant_id=tid, source="portal",
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like "
                    "Mac OS X) AppleWebKit/605.1.15 (KHTML, like "
                    "Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
                ip="203.0.113.42",
            )
            q = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert q["first_viewed_at"] is not None
            assert q["last_viewed_at"] == q["first_viewed_at"]
            assert q["view_count"] == 1
            events = await db.quote_views.find(
                {"quote_id": qid, "tenant_id": tid}, {"_id": 0},
            ).to_list(10)
            assert len(events) == 1
            e = events[0]
            assert e["source"] == "portal"
            assert e["ip"] == "203.0.113.42"
        finally:
            await _clean(db, tid, qid)

    run_test(_go)


# ─── 2 · Event doc carries ua_class ───────────────────────────
def test_record_quote_view_stamps_ua_class():
    from services.quote_view_tracker import record_quote_view

    async def _go(db):
        tid, qid = _mk_ids()
        await _clean(db, tid, qid)
        try:
            await _seed_quote(db, tid, qid, status="sent")
            # iPhone UA — must classify as "iPhone Safari".
            await record_quote_view(
                quote_id=qid, tenant_id=tid, source="link",
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like "
                    "Mac OS X) AppleWebKit/605.1.15 (KHTML, like "
                    "Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
                ip="198.51.100.1",
            )
            e = await db.quote_views.find_one(
                {"quote_id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert e is not None
            assert e["ua_class"] == "iPhone Safari"
        finally:
            await _clean(db, tid, qid)

    run_test(_go)


# ─── 3 · Auto-transition sent → viewed + audit row ────────────
def test_auto_transition_sent_to_viewed_plus_audit():
    from services.quote_view_tracker import record_quote_view

    async def _go(db):
        tid, qid = _mk_ids()
        await _clean(db, tid, qid)
        try:
            await _seed_quote(db, tid, qid, status="sent")
            await record_quote_view(
                quote_id=qid, tenant_id=tid, source="email",
                user_agent="curl/8.4.0", ip=None,
            )
            q = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert q["status"] == "viewed"
            assert q.get("auto_viewed_at") is not None
            rows = await db.audit_logs.find(
                {"quote_id": qid, "tenant_id": tid,
                    "event": "quote.auto_transition_viewed"},
                {"_id": 0},
            ).to_list(10)
            assert len(rows) == 1
            r = rows[0]
            assert r["status_before"] == "sent"
            assert r["status_after"] == "viewed"
            assert r["source"] == "email"
        finally:
            await _clean(db, tid, qid)

    run_test(_go)


# ─── 4 · Guard: draft stays draft ─────────────────────────────
def test_auto_transition_skipped_when_draft():
    from services.quote_view_tracker import record_quote_view

    async def _go(db):
        tid, qid = _mk_ids()
        await _clean(db, tid, qid)
        try:
            await _seed_quote(db, tid, qid, status="draft")
            await record_quote_view(
                quote_id=qid, tenant_id=tid, source="portal",
                user_agent="curl/8.4.0", ip=None,
            )
            q = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert q["status"] == "draft"
            audit_n = await db.audit_logs.count_documents(
                {"quote_id": qid, "tenant_id": tid,
                    "event": "quote.auto_transition_viewed"},
            )
            assert audit_n == 0
        finally:
            await _clean(db, tid, qid)

    run_test(_go)


# ─── 5 · Guard: accepted stays accepted ───────────────────────
def test_auto_transition_skipped_when_accepted():
    from services.quote_view_tracker import record_quote_view

    async def _go(db):
        tid, qid = _mk_ids()
        await _clean(db, tid, qid)
        try:
            await _seed_quote(db, tid, qid, status="accepted")
            await record_quote_view(
                quote_id=qid, tenant_id=tid, source="portal",
                user_agent="curl/8.4.0", ip=None,
            )
            q = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert q["status"] == "accepted"
            audit_n = await db.audit_logs.count_documents(
                {"quote_id": qid, "tenant_id": tid,
                    "event": "quote.auto_transition_viewed"},
            )
            assert audit_n == 0
        finally:
            await _clean(db, tid, qid)

    run_test(_go)


# ─── 6 · Guard: viewed stays viewed (idempotent re-view) ──────
def test_auto_transition_idempotent_on_viewed():
    from services.quote_view_tracker import record_quote_view

    async def _go(db):
        tid, qid = _mk_ids()
        await _clean(db, tid, qid)
        try:
            # Seed already-viewed quote.
            await _seed_quote(db, tid, qid, status="viewed")
            await record_quote_view(
                quote_id=qid, tenant_id=tid, source="portal",
                user_agent="curl/8.4.0", ip=None,
            )
            q = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert q["status"] == "viewed"
            audit_n = await db.audit_logs.count_documents(
                {"quote_id": qid, "tenant_id": tid,
                    "event": "quote.auto_transition_viewed"},
            )
            # No transition audit — the quote was already viewed
            # before this call.
            assert audit_n == 0
            # But the denorm view_count DID tick — the customer
            # still opened the quote, we just don't re-transition.
            assert q["view_count"] == 1
        finally:
            await _clean(db, tid, qid)

    run_test(_go)


# ─── 7 · Race safety — exactly ONE audit row on concurrent views
def test_concurrent_views_produce_single_audit_row():
    from services.quote_view_tracker import record_quote_view

    async def _go(db):
        tid, qid = _mk_ids()
        await _clean(db, tid, qid)
        try:
            await _seed_quote(db, tid, qid, status="sent")
            # Fire two views concurrently. Each uses a distinct
            # source so the 30 s dedupe doesn't collapse the pair
            # (the race we're testing is on the CAS-flip, not on
            # the dedupe).
            await asyncio.gather(
                record_quote_view(
                    quote_id=qid, tenant_id=tid, source="portal",
                    user_agent="curl/8.4.0", ip=None,
                ),
                record_quote_view(
                    quote_id=qid, tenant_id=tid, source="email",
                    user_agent="curl/8.4.0", ip=None,
                ),
            )
            q = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert q["status"] == "viewed"
            assert q["view_count"] == 2
            audit_n = await db.audit_logs.count_documents(
                {"quote_id": qid, "tenant_id": tid,
                    "event": "quote.auto_transition_viewed"},
            )
            assert audit_n == 1, (
                f"expected exactly one audit row from the CAS "
                f"flip, saw {audit_n}"
            )
        finally:
            await _clean(db, tid, qid)

    run_test(_go)


# ─── 8 · Empty inputs → silent no-op ───────────────────────────
def test_empty_ids_are_silent_noop():
    from services.quote_view_tracker import record_quote_view

    async def _go(db):
        # No exceptions; no rows land.
        await record_quote_view(
            quote_id="", tenant_id="T", source="link",
        )
        await record_quote_view(
            quote_id="Q", tenant_id="", source="link",
        )
        # Sanity — collection has no ghost rows for these IDs.
        n = await db.quote_views.count_documents(
            {"$or": [
                {"quote_id": "", "tenant_id": "T"},
                {"quote_id": "Q", "tenant_id": ""},
            ]},
        )
        assert n == 0

    run_test(_go)


# ─── 9 · Never raises on DB error ─────────────────────────────
def test_never_raises_even_if_insert_fails(monkeypatch):
    """Simulate a Mongo blip on the event insert. The tracker MUST
    swallow the exception and continue (so the read path never
    fails when the tracker fails).
    """
    from services import quote_view_tracker as _qvt

    async def _go(db):
        tid, qid = _mk_ids()
        await _clean(db, tid, qid)
        try:
            await _seed_quote(db, tid, qid, status="sent")

            # Patch the collection accessor so ``insert_one`` on
            # ``quote_views`` raises. Every other collection access
            # continues to work through the real ``config.db``.
            import config as _cfg
            original_db = _cfg.db

            class _ExplodingViews:
                async def find_one(self, *a, **kw):
                    # Force the dedupe check to say "no duplicate"
                    # so we reach the failing insert.
                    return None

                async def insert_one(self, *a, **kw):
                    raise RuntimeError("simulated mongo blip")

                def create_index(self, *a, **kw):  # pragma: no cover
                    return None

            class _DbProxy:
                def __getattr__(self, name):
                    if name == "quote_views":
                        return _ExplodingViews()
                    return getattr(original_db, name)

            monkeypatch.setattr(_cfg, "db", _DbProxy(), raising=True)

            # This MUST NOT raise.
            await _qvt.record_quote_view(
                quote_id=qid, tenant_id=tid, source="portal",
                user_agent="curl/8.4.0", ip=None,
            )
            # Restore before the finally cleanup so it uses real db.
            monkeypatch.setattr(_cfg, "db", original_db, raising=True)
        finally:
            await _clean(db, tid, qid)

    run_test(_go)


# ─── 10 · 30-second dedupe collapses same (quote_id, source) ──
def test_dedupe_within_thirty_seconds():
    from services.quote_view_tracker import record_quote_view

    async def _go(db):
        tid, qid = _mk_ids()
        await _clean(db, tid, qid)
        try:
            await _seed_quote(db, tid, qid, status="sent")
            # Two views, same (quote_id, source), back-to-back —
            # second call MUST be swallowed by the 30 s dedupe.
            await record_quote_view(
                quote_id=qid, tenant_id=tid, source="email",
                user_agent="curl/8.4.0", ip=None,
            )
            await record_quote_view(
                quote_id=qid, tenant_id=tid, source="email",
                user_agent="curl/8.4.0", ip=None,
            )
            events_n = await db.quote_views.count_documents(
                {"quote_id": qid, "tenant_id": tid},
            )
            assert events_n == 1
            q = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid}, {"_id": 0},
            )
            assert q["view_count"] == 1
        finally:
            await _clean(db, tid, qid)

    run_test(_go)


# ─── 11 · Cross-tenant guard — tenant B never touches tenant A
def test_cross_tenant_call_does_not_touch_quote():
    from services.quote_view_tracker import record_quote_view

    async def _go(db):
        tid_a, qid = _mk_ids()
        tid_b = "TEST_qv_tenant_B_" + uuid.uuid4().hex[:8]
        await _clean(db, tid_a, qid)
        await db.quote_views.delete_many({"tenant_id": tid_b})
        try:
            # Seed quote under tenant A.
            await _seed_quote(db, tid_a, qid, status="sent")
            # Fire a view claiming tenant B — the denorm update
            # filter includes ``tenant_id`` so tenant A's row is
            # untouched. The event row DOES land under tenant B
            # (that's expected — the event log is a raw feed; the
            # denorm guard is what matters for stat integrity).
            await record_quote_view(
                quote_id=qid, tenant_id=tid_b, source="portal",
                user_agent="curl/8.4.0", ip=None,
            )
            q = await db.quotes.find_one(
                {"id": qid, "tenant_id": tid_a}, {"_id": 0},
            )
            # Tenant A quote MUST be untouched.
            assert q["status"] == "sent"
            assert "first_viewed_at" not in q or q.get(
                "first_viewed_at") is None
            assert q.get("view_count", 0) == 0
            # And zero audit rows for either tenant on this qid.
            audit_n = await db.audit_logs.count_documents(
                {"quote_id": qid,
                    "event": "quote.auto_transition_viewed"},
            )
            assert audit_n == 0
        finally:
            await _clean(db, tid_a, qid)
            await db.quote_views.delete_many({"tenant_id": tid_b})

    run_test(_go)
