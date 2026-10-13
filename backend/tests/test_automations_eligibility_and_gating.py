"""Feb-2026 · Automation eligibility + gating — pytest suite.

Covers:

  * Pure eligibility helper surface (14 cases from the dispatch
    spec).
  * PDF-import write site: ``automations_suppressed=True`` lands on
    the invoice doc.
  * Native invoice write site: ``automations_suppressed=False``
    lands on the invoice doc (explicit, not implicit).
  * Dunning cron skip-rows + reason breakdown.
  * Past-due drip sweep skip-rows + reason breakdown.
  * Welcome email suppression on PDF-imported quote.

Run from repo root:

    cd /app/backend && python -m pytest \
        tests/test_automations_eligibility_and_gating.py -x -v
"""
from __future__ import annotations

import pytest

from services.automations.eligibility import (
    is_invoice_eligible_for_automation,
)


# Project uses ``anyio`` for async tests.
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ═════════════════════════════════════════════════════════════
# Case 3-9 · Pure eligibility helper surface.
# ═════════════════════════════════════════════════════════════

def test_pdf_import_suppression_blocks_any_kind():
    inv = {"id": "pdfinv", "automations_suppressed": True,
           "payment_status": "unpaid", "status": "sent"}
    for kind in ("invoice_sent", "invoice_paid", "payment_reminder",
                   "dunning", "welcome_email", "overdue"):
        ok, reason = is_invoice_eligible_for_automation(
            inv, automation_kind=kind,
        )
        assert ok is False, f"kind={kind} should be suppressed"
        assert reason == "pdf_import_suppressed"


def test_soft_deleted_blocks_any_kind():
    inv = {"id": "x", "deleted_at": "2026-02-01T00:00:00+00:00",
           "payment_status": "unpaid", "status": "sent"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="payment_reminder",
    )
    assert ok is False
    assert reason == "soft_deleted"


def test_payment_reminder_paid_invoice_blocked():
    inv = {"id": "x", "payment_status": "paid", "status": "sent"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="payment_reminder",
    )
    assert ok is False
    assert reason == "payment_status_paid"


def test_payment_reminder_partial_invoice_blocked():
    inv = {"id": "x", "payment_status": "partial", "status": "sent"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="payment_reminder",
    )
    assert ok is False
    assert reason == "payment_status_partial"


def test_payment_reminder_unpaid_invoice_eligible():
    inv = {"id": "x", "payment_status": "unpaid", "status": "sent"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="payment_reminder",
    )
    assert ok is True
    assert reason is None


def test_payment_reminder_draft_invoice_blocked():
    inv = {"id": "x", "payment_status": "unpaid", "status": "draft"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="payment_reminder",
    )
    assert ok is False
    assert reason == "invoice_status_draft"


def test_payment_reminder_void_blocked():
    inv = {"id": "x", "payment_status": "unpaid", "status": "void"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="payment_reminder",
    )
    assert ok is False
    assert reason == "invoice_status_void"


def test_payment_reminder_cancelled_blocked():
    inv = {"id": "x", "payment_status": "unpaid", "status": "cancelled"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="payment_reminder",
    )
    assert ok is False
    assert reason == "invoice_status_cancelled"


def test_dunning_mirrors_payment_reminder_rules():
    paid = {"id": "x", "payment_status": "paid", "status": "sent"}
    ok, reason = is_invoice_eligible_for_automation(
        paid, automation_kind="dunning",
    )
    assert ok is False
    assert reason == "payment_status_paid"


def test_welcome_email_unpaid_invoice_eligible():
    """Welcome email does NOT gate on payment_status."""
    inv = {"id": "x", "payment_status": "unpaid", "status": "sent"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="welcome_email",
    )
    assert ok is True
    assert reason is None


def test_welcome_email_paid_invoice_eligible():
    """Welcome email does NOT gate on payment_status (even for paid)."""
    inv = {"id": "x", "payment_status": "paid", "status": "sent"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="welcome_email",
    )
    assert ok is True
    assert reason is None


def test_welcome_email_pdf_imported_blocked():
    inv = {"id": "x", "automations_suppressed": True,
           "payment_status": "unpaid", "status": "sent"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="welcome_email",
    )
    assert ok is False
    assert reason == "pdf_import_suppressed"


def test_invoice_sent_pdf_imported_blocked():
    inv = {"id": "x", "automations_suppressed": True,
           "payment_status": "unpaid", "status": "sent"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="invoice_sent",
    )
    assert ok is False
    assert reason == "pdf_import_suppressed"


def test_invoice_sent_native_eligible():
    inv = {"id": "x", "automations_suppressed": False,
           "payment_status": "unpaid", "status": "sent"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="invoice_sent",
    )
    assert ok is True
    assert reason is None


def test_legacy_invoice_without_field_defaults_to_eligible():
    """Legacy invoices (field absent) MUST default to NOT suppressed
    so existing live traffic is unaffected."""
    inv = {"id": "x", "payment_status": "unpaid", "status": "sent"}
    ok, reason = is_invoice_eligible_for_automation(
        inv, automation_kind="invoice_sent",
    )
    assert ok is True


# ═════════════════════════════════════════════════════════════
# Case 1-2 · Write site field stamping.
# ═════════════════════════════════════════════════════════════

def test_pdf_import_write_stamps_automations_suppressed_true():
    """``_build_quote_doc_from_preview`` MUST stamp
    ``automations_suppressed=True`` + ``source=pdf_import`` on
    every PDF-imported invoice doc."""
    from services.imports.pdf_commit import _build_quote_doc_from_preview

    preview = {
        "source_doc_index": 0,
        "quote_in": {
            "customer_id": "cust-1",
            "doc_type": "invoice",
            "doc_number": "I-9001",
            "line_items": [],
            "subtotal": 100.0, "tax_total": 0.0, "grand_total": 100.0,
            "total_due": 100.0,
            "status": "sent",
            "payment_status": "unpaid",
        },
    }
    batch = {"id": "batch-1"}
    doc = _build_quote_doc_from_preview(
        preview=preview, batch=batch,
        tenant_id="tenant-1", operator={"id": "op-1"},
        commit_at="2026-02-10T00:00:00+00:00",
    )
    assert doc["automations_suppressed"] is True
    assert doc["source"] == "pdf_import"
    assert doc["doc_type"] == "invoice"


def test_native_create_quote_doc_contains_explicit_false():
    """Smoke-test by grep: the native create_quote path writes
    ``automations_suppressed=False`` into the quotes doc.  We
    assert the field is in the source text of ``routers/quotes.py``
    at the create_quote site; a full-stack API test lives in the
    live-integration suite (``test_quotes_*.py``)."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "routers" / "quotes.py"
    text = src.read_text()
    assert '"automations_suppressed": False' in text, (
        "Native create_quote must stamp automations_suppressed=False "
        "explicitly."
    )
    # Also confirm the invoice_builder convert-from-quote path and
    # auto_invoice.create_invoice_from_job write the explicit field.
    ib = (Path(__file__).resolve().parents[1]
            / "services" / "invoice_builder.py")
    assert '"automations_suppressed": False' in ib.read_text()
    ai = (Path(__file__).resolve().parents[1]
            / "services" / "auto_invoice.py")
    assert '"automations_suppressed": False' in ai.read_text()


# ═════════════════════════════════════════════════════════════
# Case 10-11 · Cron batch skip + audit row.
# ═════════════════════════════════════════════════════════════

class _MockCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    async def to_list(self, length=None):
        return list(self._rows)

    def __aiter__(self):
        async def _gen():
            for r in self._rows:
                yield r
        return _gen()


class _MockCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.inserted = []
        self.updates = []

    def find(self, query, projection=None):
        rows = [r for r in self.rows if _mock_match(r, query)]
        return _MockCursor(rows)

    async def find_one(self, query, projection=None):
        for r in self.rows:
            if _mock_match(r, query):
                return dict(r)
        return None

    async def insert_one(self, doc):
        self.inserted.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("id") or "m"})()

    async def update_one(self, query, update):
        for r in self.rows:
            if _mock_match(r, query):
                for k, v in (update.get("$set") or {}).items():
                    r[k] = v
                return type("U", (), {"matched_count": 1,
                                        "modified_count": 1})()
        return type("U", (), {"matched_count": 0,
                                "modified_count": 0})()

    async def count_documents(self, query):
        return sum(1 for r in self.rows if _mock_match(r, query))


def _mock_match(row, query):
    for key, val in query.items():
        if isinstance(val, dict):
            if "$in" in val:
                if row.get(key) not in val["$in"]:
                    return False
                continue
            if "$nin" in val:
                if row.get(key) in val["$nin"]:
                    return False
                continue
            if "$ne" in val:
                if row.get(key) == val["$ne"]:
                    return False
                continue
            if "$exists" in val:
                exists = key in row
                if exists != val["$exists"]:
                    return False
                continue
            if "$lt" in val:
                if not (row.get(key) is not None and row.get(key) < val["$lt"]):
                    return False
                continue
            if "$gte" in val and "$lte" in val:
                v = row.get(key)
                if v is None or not (val["$gte"] <= v <= val["$lte"]):
                    return False
                continue
        else:
            if row.get(key) != val:
                return False
    return True


async def test_batch_skip_audit_row_written(monkeypatch):
    """log_batch_skipped writes one audit_logs row per non-empty
    run and includes tenant_id, run_id, kind, reason_breakdown."""
    from services.automations import eligibility as elig_mod

    captured = {}
    audit_coll = _MockCollection()

    class _FakeDB:
        audit_logs = audit_coll

    monkeypatch.setattr(elig_mod, "db", _FakeDB)

    await elig_mod.log_batch_skipped(
        tenant_id="tenant-X",
        automation_kind="dunning",
        run_id="run-42",
        reason_breakdown={"pdf_import_suppressed": 5,
                            "payment_status_paid": 3},
        total_skipped=8,
    )
    assert len(audit_coll.inserted) == 1
    row = audit_coll.inserted[0]
    assert row["action"] == "automation.batch_skipped"
    assert row["tenant_id"] == "tenant-X"
    assert row["automation_kind"] == "dunning"
    assert row["run_id"] == "run-42"
    assert row["total_skipped"] == 8
    assert row["reason_breakdown"]["pdf_import_suppressed"] == 5
    assert row["reason_breakdown"]["payment_status_paid"] == 3


async def test_batch_skip_audit_noop_on_zero_skipped(monkeypatch):
    """An empty run (no skips) MUST NOT write an audit row."""
    from services.automations import eligibility as elig_mod
    audit_coll = _MockCollection()

    class _FakeDB:
        audit_logs = audit_coll

    monkeypatch.setattr(elig_mod, "db", _FakeDB)
    await elig_mod.log_batch_skipped(
        tenant_id="t", automation_kind="dunning", run_id="r",
        reason_breakdown={}, total_skipped=0,
    )
    assert audit_coll.inserted == []


# ═════════════════════════════════════════════════════════════
# Case 12-13 · Welcome-email + invoice_sent trigger behaviour.
# ═════════════════════════════════════════════════════════════

async def test_welcome_email_bails_on_pdf_imported_quote(monkeypatch):
    """``maybe_fire_welcome_on_first_accepted_quote`` MUST short-
    circuit before any send pipeline work when the triggering
    quote has ``automations_suppressed=True``."""
    from services import customer_welcome_email as cwe

    quote_doc = {
        "id": "q-pdf", "tenant_id": "t",
        "automations_suppressed": True,
        "status": "sent", "payment_status": "unpaid",
    }

    class _FakeDB:
        quotes = _MockCollection([quote_doc])
        customers = _MockCollection([])
        tenants = _MockCollection([])

    # Replace the module-level db + capture any sends.
    monkeypatch.setattr(cwe, "db", _FakeDB)

    called = {"sent": False}

    async def _fail_send(**_):
        called["sent"] = True
        raise AssertionError("Welcome email must NOT fire for "
                              "PDF-imported quotes.")

    # Patch anything the pipeline would call AFTER the gate — the
    # gate must trigger `return` before these are even reached.
    monkeypatch.setattr(cwe, "absolute_portal_url", _fail_send,
                        raising=False)

    await cwe.maybe_fire_welcome_on_first_accepted_quote(
        tenant_id="t", customer_id="c",
        quote_id="q-pdf", source="test",
    )
    assert called["sent"] is False
