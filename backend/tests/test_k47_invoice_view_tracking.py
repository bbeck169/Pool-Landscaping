"""Phase K47 · Feb-2026 — Backend tests for invoice-view tracking.

The project does not use pytest-asyncio (see K43 for the wider
rationale — Motor futures are tied to the event loop that
created them, so async tests wrap coroutines in explicit
``asyncio.run(...)`` calls). This suite follows the same pattern:
pure-Python fakes for the two collections we care about
(``invoice_views``, ``quotes``) and one asyncio.run wrapper per
assertion.

Coverage:
* ``record_invoice_view`` inserts a doc + updates denorm fields.
* 30-second dedupe window per (invoice_id, source).
* Distinct sources within the window ARE recorded (email + portal).
* Invalid ``source`` values collapse to ``"link"``.
* ``fetch_invoice_views_summary`` returns the expected shape.
* Empty invoice_id / tenant_id silently no-op.
* User-Agent field truncated at 512 chars.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class _FakeInvoiceViewsCol:
    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    async def insert_one(self, doc):
        self.rows.append(doc)
        return SimpleNamespace(inserted_id="x")

    async def find_one(self, filt, projection=None):
        for r in self.rows:
            if _match(r, filt):
                return dict(r)
        return None

    def find(self, filt, projection=None):
        matching = [r for r in self.rows if _match(r, filt)]
        return _FakeCursor(matching)

    async def create_index(self, *args, **kwargs):
        return "idx"


class _FakeQuotesCol:
    def __init__(self, invoice_docs):
        self.invoice_docs = invoice_docs

    async def update_one(self, filt, update):
        for inv in self.invoice_docs:
            if all(inv.get(k) == v for k, v in filt.items()):
                if "$min" in update:
                    for k, v in update["$min"].items():
                        if inv.get(k) is None or v < inv.get(k):
                            inv[k] = v
                if "$max" in update:
                    for k, v in update["$max"].items():
                        if inv.get(k) is None or v > inv.get(k):
                            inv[k] = v
                if "$inc" in update:
                    for k, v in update["$inc"].items():
                        inv[k] = (inv.get(k) or 0) + v
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def find_one(self, filt, projection=None):
        for inv in self.invoice_docs:
            if all(inv.get(k) == v for k, v in filt.items()):
                return dict(inv)
        return None


def _match(row: Dict[str, Any], filt: Dict[str, Any]) -> bool:
    for k, v in filt.items():
        val = row.get(k)
        if isinstance(v, dict):
            for op, opv in v.items():
                if op == "$gte" and not (val is not None and val >= opv):
                    return False
        else:
            if val != v:
                return False
    return True


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
    def sort(self, *args, **kwargs):
        self.rows = sorted(self.rows, key=lambda r: r.get("viewed_at") or "",
                             reverse=True)
        return self
    def limit(self, n):
        self.rows = self.rows[:n]
        return self
    async def to_list(self, length=None):
        return list(self.rows)


class _FakeDB:
    def __init__(self):
        self._invoice_docs = [
            {"id": "inv-1", "tenant_id": "t-1", "doc_type": "invoice"},
        ]
        self.invoice_views = _FakeInvoiceViewsCol()
        self.quotes = _FakeQuotesCol(self._invoice_docs)


@pytest.fixture
def fake_db(monkeypatch):
    fdb = _FakeDB()
    import services.invoice_view_tracker as ivt
    monkeypatch.setattr(ivt, "db", fdb)
    return fdb


def test_record_invoice_view_inserts_and_denormalizes(fake_db):
    from services.invoice_view_tracker import record_invoice_view

    _run(record_invoice_view(
        invoice_id="inv-1", tenant_id="t-1", source="email",
        user_agent="Mozilla/5.0", ip="1.2.3.4",
    ))
    assert len(fake_db.invoice_views.rows) == 1
    row = fake_db.invoice_views.rows[0]
    assert row["invoice_id"] == "inv-1"
    assert row["source"] == "email"
    assert row["user_agent"] == "Mozilla/5.0"

    inv = fake_db._invoice_docs[0]
    assert inv["view_count"] == 1
    assert inv["first_viewed_at"] == inv["last_viewed_at"]
    assert inv["first_viewed_at"] == row["viewed_at"]


def test_dedupe_within_30s_same_source(fake_db):
    from services.invoice_view_tracker import record_invoice_view

    _run(record_invoice_view(invoice_id="inv-1", tenant_id="t-1", source="email"))
    _run(record_invoice_view(invoice_id="inv-1", tenant_id="t-1", source="email"))
    _run(record_invoice_view(invoice_id="inv-1", tenant_id="t-1", source="email"))

    assert len(fake_db.invoice_views.rows) == 1
    assert fake_db._invoice_docs[0]["view_count"] == 1


def test_dedupe_scoped_to_source(fake_db):
    from services.invoice_view_tracker import record_invoice_view

    _run(record_invoice_view(invoice_id="inv-1", tenant_id="t-1", source="email"))
    _run(record_invoice_view(invoice_id="inv-1", tenant_id="t-1", source="portal"))

    assert len(fake_db.invoice_views.rows) == 2
    assert fake_db._invoice_docs[0]["view_count"] == 2


def test_unknown_source_collapses_to_link(fake_db):
    from services.invoice_view_tracker import record_invoice_view

    _run(record_invoice_view(
        invoice_id="inv-1", tenant_id="t-1", source="attacker-controlled"))
    assert fake_db.invoice_views.rows[0]["source"] == "link"


def test_none_source_becomes_link(fake_db):
    from services.invoice_view_tracker import record_invoice_view

    _run(record_invoice_view(invoice_id="inv-1", tenant_id="t-1", source=None))
    assert fake_db.invoice_views.rows[0]["source"] == "link"


def test_empty_ids_noop(fake_db):
    from services.invoice_view_tracker import record_invoice_view

    _run(record_invoice_view(invoice_id="", tenant_id="t-1", source="email"))
    _run(record_invoice_view(invoice_id="inv-1", tenant_id="", source="email"))

    assert len(fake_db.invoice_views.rows) == 0


def test_user_agent_truncated(fake_db):
    from services.invoice_view_tracker import record_invoice_view

    long_ua = "x" * 1024
    _run(record_invoice_view(
        invoice_id="inv-1", tenant_id="t-1", source="email", user_agent=long_ua))
    assert len(fake_db.invoice_views.rows[0]["user_agent"]) == 512


def test_fetch_summary_shape(fake_db):
    from services.invoice_view_tracker import (
        record_invoice_view, fetch_invoice_views_summary,
    )

    _run(record_invoice_view(invoice_id="inv-1", tenant_id="t-1", source="email"))
    _run(record_invoice_view(invoice_id="inv-1", tenant_id="t-1", source="portal"))

    summary = _run(fetch_invoice_views_summary(
        invoice_id="inv-1", tenant_id="t-1"))

    assert summary["invoice_id"] == "inv-1"
    assert summary["view_count"] == 2
    assert summary["first_viewed_at"] is not None
    assert summary["last_viewed_at"] is not None
    assert len(summary["events"]) == 2
    assert summary["events"][0]["viewed_at"] >= summary["events"][1]["viewed_at"]
    for ev in summary["events"]:
        assert "_id" not in ev


def test_pay_link_builder_forwards_src(monkeypatch):
    """Phase K47 · Feb-2026 — Regression guard on the new ``src`` kwarg."""
    from services import pay_link_builder as plb

    monkeypatch.setattr(plb, "issue_invoice_magic_token",
                          lambda *a, **kw: "test-token")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.com")

    plain = plb.build_pay_now_url("inv-1", "t-1")
    assert plain.endswith("token=test-token")
    assert "src=" not in plain

    email = plb.build_pay_now_url("inv-1", "t-1", src="email")
    assert email.endswith("&src=email")

    sms = plb.build_pay_now_url("inv-1", "t-1", src="sms")
    assert sms.endswith("&src=sms")
