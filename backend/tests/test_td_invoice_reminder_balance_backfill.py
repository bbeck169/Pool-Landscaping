"""TD-invoice-reminder-balance-backfill · Feb-2026 — pytest suite.

Locks the behavior of the one-shot migration script at
``backend/migrations/backfill_invoice_reminder_balance_v1.py``.
Uses an in-memory ``FakeDB`` that mimics the subset of the motor
``AsyncIOMotorDatabase`` API the migration exercises
(``marketing_templates`` + ``tenants`` + ``migration_runs``) so the
suite stays hermetic (no mongod process, no mongomock) — matches
the convention of ``tests/test_td_quiet_hours_cron_tick_recovery.py``.

Cases:

  1. Dry-run on a mixed fixture (3 operator-authored past-due email
     + sms rows with ``{{INVOICE_TOTAL}}`` + balance body; 1 receipt-
     style row with ``{{INVOICE_TOTAL}}`` + total body; 1 past-due
     reminder already on ``{{INVOICE_BALANCE}}``) → predicts rewrite=3,
     skip reasons classified.
  2. Apply pass → 3 rows rewritten; receipt + already-migrated rows
     untouched; counts match the dry-run prediction.
  3. Second apply = all-zero (idempotency; locked by test).
  4. Cross-tenant isolation: tenant A rows rewrite; tenant B rows
     with the same shape are NOT touched when scope is tenant A.
  5. ``--include-non-balance-semantic`` escape hatch: forces rewrite
     on a row whose body/subject carries ``{{INVOICE_TOTAL}}`` but
     has no balance word.
  6. Fail-closed-per-tenant: a tenant whose cursor raises mid-scan
     records the error + ``tenants_with_errors`` bump, but the
     remaining tenants still process cleanly.
  7. Preserve-on-edit: a row whose operator reshaped the body to
     omit the balance word is classified as ``no_balance_semantic``
     and left unchanged.
  8. Multi-field rewrite: ``{{INVOICE_TOTAL}}`` in subject only AND
     in body only AND in both — all three forms are rewritten; a
     tenant that stuffed the token into the subject but kept a
     balance-word body still rewrites both fields.
  9. SMS rows (``subject = None``) are not corrupted by the write
     path — subject stays ``None`` when it started as ``None``.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from typing import Any, Dict, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


# ─── Hermetic FakeDB (mimics the subset of motor the migration uses) ──
class _FakeCursor:
    def __init__(self, rows: List[Dict[str, Any]],
                   projection: Optional[Dict[str, Any]] = None):
        self._rows = list(rows)
        self._projection = projection

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for r in self._rows:
            yield _project(r, self._projection)

    async def to_list(self, _max):  # noqa: D401
        return [_project(r, self._projection) for r in self._rows]

    def sort(self, *_a, **_kw):  # pragma: no cover (unused)
        return self

    def limit(self, _n):  # pragma: no cover (unused)
        return self


def _project(row: Dict[str, Any],
              projection: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not projection:
        return dict(row)
    include = {k for k, v in projection.items() if v == 1}
    include.discard("_id")
    return {k: v for k, v in row.items() if k in include}


class _MatchHelper:
    """Tiny subset of Mongo match evaluation sufficient for this
    migration's queries ($and / $or / $ne / $exists / $in / scalar)."""
    @staticmethod
    def matches(row: Dict[str, Any], q: Dict[str, Any]) -> bool:
        for k, v in q.items():
            if k == "$and":
                if not all(_MatchHelper.matches(row, sub) for sub in v):
                    return False
                continue
            if k == "$or":
                if not any(_MatchHelper.matches(row, sub) for sub in v):
                    return False
                continue
            if isinstance(v, dict):
                for op, operand in v.items():
                    if op == "$ne":
                        if row.get(k) == operand:
                            return False
                    elif op == "$exists":
                        if (k in row) != bool(operand):
                            return False
                    elif op == "$in":
                        if row.get(k) not in operand:
                            return False
                    elif op == "$eq":
                        if row.get(k) != operand:
                            return False
                    else:
                        return False
                continue
            if row.get(k) != v:
                return False
        return True


class _FakeCollection:
    def __init__(self, name: str, fail_cursor: bool = False):
        self.name = name
        self.rows: List[Dict[str, Any]] = []
        self._fail_cursor = fail_cursor

    def find(self, query: Dict[str, Any],
              projection: Optional[Dict[str, Any]] = None):
        if self._fail_cursor:
            raise RuntimeError("fake cursor failure")
        matches = [r for r in self.rows
                   if _MatchHelper.matches(r, query)]
        return _FakeCursor(matches, projection)

    async def update_one(self, query: Dict[str, Any],
                           update: Dict[str, Any]):
        for r in self.rows:
            if _MatchHelper.matches(r, query):
                r.update(update.get("$set") or {})
                return _UpdateResult(1, 1, False)
        return _UpdateResult(0, 0, False)

    async def insert_one(self, doc: Dict[str, Any]):
        self.rows.append(dict(doc))
        return _InsertResult(doc.get("id") or str(uuid.uuid4()))

    async def find_one(self, query: Dict[str, Any],
                         projection: Optional[Dict[str, Any]] = None):
        for r in self.rows:
            if _MatchHelper.matches(r, query):
                return _project(r, projection)
        return None


class _UpdateResult:
    def __init__(self, matched: int, modified: int, upserted: bool):
        self.matched_count = matched
        self.modified_count = modified
        self.upserted_id = None


class _InsertResult:
    def __init__(self, iid):
        self.inserted_id = iid


class _FakeDB:
    def __init__(self):
        self.marketing_templates = _FakeCollection("marketing_templates")
        self.tenants = _FakeCollection("tenants")
        self.migration_runs = _FakeCollection("migration_runs")

    def __getattr__(self, name):  # pragma: no cover (defensive)
        raise AttributeError(name)


# ─── Fixtures ─────────────────────────────────────────────────────────
TENANT_A = "tenant-A"
TENANT_B = "tenant-B"


def _seed_tenants(db: _FakeDB, *tids: str):
    for t in tids:
        db.tenants.rows.append({"id": t, "active": True})


def _row(**overrides) -> Dict[str, Any]:
    defaults = {
        "id":        str(uuid.uuid4()),
        "tenant_id": TENANT_A,
        "system_key": "system_tpl_invoice_past_due_7d_email",
        "code":      None,
        "channel":   "email",
        "subject":   "Reminder: invoice {{INVOICE_NUMBER}}",
        "body":      ("Hi {{CUSTOMER_FIRST_NAME}}, your outstanding "
                       "balance of {{INVOICE_TOTAL}} is 7 days past "
                       "due."),
        "active":    True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return defaults


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── Test cases ───────────────────────────────────────────────────────
def test_dry_run_predicts_rewrite_counts_without_mutation():
    from migrations.backfill_invoice_reminder_balance_v1 import (
        backfill_invoice_reminder_balance,
    )
    db = _FakeDB()
    _seed_tenants(db, TENANT_A)
    # 3 operator-authored past-due reminder rows: email + sms + email-override
    r1 = _row()
    r2 = _row(
        system_key="system_tpl_invoice_past_due_7d_sms",
        channel="sms",
        subject=None,
        body=("Reminder: your outstanding balance of {{INVOICE_TOTAL}} "
              "is past due.  Pay: {{PAY_LINK}}"),
    )
    r3 = _row(
        system_key=None,
        code="invoice_reminder_email",
        subject="Invoice reminder — {{INVOICE_NUMBER}}",
        body=("Your invoice has an outstanding balance of "
              "{{INVOICE_TOTAL}}."),
    )
    # Already-migrated past-due reminder (should skip predicate).
    r_already = _row(
        subject="Reminder: invoice {{INVOICE_NUMBER}}",
        body="Your outstanding balance of {{INVOICE_BALANCE}} is past due.",
    )
    # Receipt-shape row with {{INVOICE_TOTAL}} + total body — stays
    # inside the invoice-reminder-class query (same system_key) but
    # the operator reshaped the semantic to mean total.  Preserved.
    r_receipt = _row(
        subject="Receipt for {{INVOICE_NUMBER}}",
        body="Thanks — your invoice total was {{INVOICE_TOTAL}}.",
    )
    db.marketing_templates.rows.extend([r1, r2, r3, r_already, r_receipt])

    out = _run(backfill_invoice_reminder_balance(
        db, tenant_id=TENANT_A, dry_run=True,
    ))

    assert out["dry_run"] is True
    assert out["totals"]["rows_scanned"] == 5
    assert out["totals"]["rows_matched"] == 3
    assert out["totals"]["rows_rewritten"] == 0  # dry-run never writes
    assert out["totals"]["rows_skipped"] == 2
    reasons = out["totals"]["skip_reasons"]
    assert reasons["no_invoice_total_token"] == 1   # r_already
    assert reasons["no_balance_semantic"] == 1      # r_receipt

    # No row was mutated.
    assert "{{INVOICE_TOTAL}}" in r1["body"]
    assert "{{INVOICE_TOTAL}}" in r2["body"]
    assert "{{INVOICE_TOTAL}}" in r3["body"]
    # And no audit row written on dry-run.
    assert db.migration_runs.rows == []


def test_apply_rewrites_matched_rows_only():
    from migrations.backfill_invoice_reminder_balance_v1 import (
        backfill_invoice_reminder_balance,
    )
    db = _FakeDB()
    _seed_tenants(db, TENANT_A)
    r_match = _row()
    r_receipt = _row(
        subject="Receipt for {{INVOICE_NUMBER}}",
        body="Thanks — your invoice total was {{INVOICE_TOTAL}}.",
    )
    r_already = _row(
        body="Your outstanding balance of {{INVOICE_BALANCE}} is past due.",
    )
    db.marketing_templates.rows.extend([r_match, r_receipt, r_already])

    out = _run(backfill_invoice_reminder_balance(
        db, tenant_id=TENANT_A, dry_run=False,
    ))

    assert out["totals"]["rows_matched"] == 1
    assert out["totals"]["rows_rewritten"] == 1
    assert "{{INVOICE_BALANCE}}" in r_match["body"]
    assert "{{INVOICE_TOTAL}}" not in r_match["body"]
    # Receipt + already-migrated untouched.
    assert "{{INVOICE_TOTAL}}" in r_receipt["body"]
    assert "{{INVOICE_BALANCE}}" in r_already["body"]
    # Audit row emitted.
    assert len(db.migration_runs.rows) == 1
    audit = db.migration_runs.rows[0]
    assert audit["name"] == "backfill_invoice_reminder_balance_v1"
    assert audit["tenant_id"] == TENANT_A
    assert audit["status"] == "ok"
    assert audit["summary"]["rows_rewritten"] == 1


def test_second_apply_is_idempotent_noop():
    from migrations.backfill_invoice_reminder_balance_v1 import (
        backfill_invoice_reminder_balance,
    )
    db = _FakeDB()
    _seed_tenants(db, TENANT_A)
    db.marketing_templates.rows.append(_row())

    first = _run(backfill_invoice_reminder_balance(
        db, tenant_id=TENANT_A, dry_run=False,
    ))
    assert first["totals"]["rows_rewritten"] == 1

    second = _run(backfill_invoice_reminder_balance(
        db, tenant_id=TENANT_A, dry_run=False,
    ))
    assert second["totals"]["rows_matched"] == 0
    assert second["totals"]["rows_rewritten"] == 0
    # The already-rewritten row shows up as the no_invoice_total_token
    # skip reason — predicate-level idempotency.
    assert second["totals"]["skip_reasons"]["no_invoice_total_token"] == 1


def test_cross_tenant_isolation():
    from migrations.backfill_invoice_reminder_balance_v1 import (
        backfill_invoice_reminder_balance,
    )
    db = _FakeDB()
    _seed_tenants(db, TENANT_A, TENANT_B)
    row_a = _row(tenant_id=TENANT_A)
    row_b = _row(tenant_id=TENANT_B)
    db.marketing_templates.rows.extend([row_a, row_b])

    _run(backfill_invoice_reminder_balance(
        db, tenant_id=TENANT_A, dry_run=False,
    ))

    assert "{{INVOICE_BALANCE}}" in row_a["body"]
    assert "{{INVOICE_TOTAL}}" in row_b["body"]
    # Audit row only for tenant A.
    assert len(db.migration_runs.rows) == 1
    assert db.migration_runs.rows[0]["tenant_id"] == TENANT_A


def test_include_non_balance_semantic_forces_rewrite():
    from migrations.backfill_invoice_reminder_balance_v1 import (
        backfill_invoice_reminder_balance,
    )
    db = _FakeDB()
    _seed_tenants(db, TENANT_A)
    # Body carries {{INVOICE_TOTAL}} but no balance word.
    row = _row(
        subject="Your invoice is ready",
        body="Hi — your invoice amount is {{INVOICE_TOTAL}}.  Pay here.",
    )
    db.marketing_templates.rows.append(row)

    # Default run: predicate skips.
    out = _run(backfill_invoice_reminder_balance(
        db, tenant_id=TENANT_A, dry_run=True,
    ))
    assert out["totals"]["rows_matched"] == 0
    assert out["totals"]["skip_reasons"]["no_balance_semantic"] == 1

    # Escape-hatch run: forced rewrite.
    out = _run(backfill_invoice_reminder_balance(
        db, tenant_id=TENANT_A, dry_run=False,
        include_non_balance_semantic=True,
    ))
    assert out["totals"]["rows_rewritten"] == 1
    assert "{{INVOICE_BALANCE}}" in row["body"]
    audit = db.migration_runs.rows[0]
    assert audit["include_non_balance_semantic"] is True


def test_fail_closed_per_tenant():
    from migrations.backfill_invoice_reminder_balance_v1 import (
        backfill_invoice_reminder_balance,
    )
    db = _FakeDB()
    _seed_tenants(db, TENANT_A, TENANT_B)
    row_b = _row(tenant_id=TENANT_B)
    db.marketing_templates.rows.append(row_b)

    # Monkey-patch the collection's ``find`` to fail ONLY when the
    # tenant filter is tenant A so tenant B still processes cleanly.
    original_find = db.marketing_templates.find

    def _fail_only_tenant_a(query, projection=None):
        # The migration's match query is ``{"$and": [anchor_clause,
        # {"tenant_id": tid}]}`` — recover the inner tenant_id.
        for sub in query.get("$and", []):
            if "tenant_id" in sub and sub["tenant_id"] == TENANT_A:
                raise RuntimeError("boom-tenant-A")
        return original_find(query, projection)

    db.marketing_templates.find = _fail_only_tenant_a

    out = _run(backfill_invoice_reminder_balance(
        db, all_tenants=True, dry_run=False,
    ))

    assert out["totals"]["tenants_with_errors"] == 1
    assert out["totals"]["rows_rewritten"] == 1  # tenant B still processed
    assert "{{INVOICE_BALANCE}}" in row_b["body"]
    # Both tenants got audit rows (fail-closed-per-tenant records
    # partial counts, doesn't skip audit).
    assert len(db.migration_runs.rows) == 2
    by_tid = {r["tenant_id"]: r for r in db.migration_runs.rows}
    assert by_tid[TENANT_A]["status"] == "error"
    assert by_tid[TENANT_B]["status"] == "ok"


def test_preserve_on_edit_strict_predicate_skips_reshaped_body():
    from migrations.backfill_invoice_reminder_balance_v1 import (
        backfill_invoice_reminder_balance,
    )
    db = _FakeDB()
    _seed_tenants(db, TENANT_A)
    # Operator reshaped the body completely — no balance word, no
    # ``outstanding`` / ``owed`` / ``past due``.  Predicate skips.
    row = _row(
        subject="Reminder — tap to pay",
        body=("Hi — please settle invoice {{INVOICE_NUMBER}} totaling "
               "{{INVOICE_TOTAL}}.  Thanks."),
    )
    db.marketing_templates.rows.append(row)

    out = _run(backfill_invoice_reminder_balance(
        db, tenant_id=TENANT_A, dry_run=False,
    ))

    assert out["totals"]["rows_rewritten"] == 0
    assert out["totals"]["skip_reasons"]["no_balance_semantic"] == 1
    assert "{{INVOICE_TOTAL}}" in row["body"]  # untouched


def test_multi_field_rewrite_covers_subject_and_body():
    from migrations.backfill_invoice_reminder_balance_v1 import (
        backfill_invoice_reminder_balance,
    )
    db = _FakeDB()
    _seed_tenants(db, TENANT_A)
    # Row 1: token in subject only, balance word in body.
    r_subj = _row(
        subject="Outstanding balance {{INVOICE_TOTAL}}",
        body=("Hi — your outstanding balance is listed above.  Pay: "
               "{{PAY_LINK}}"),
    )
    # Row 2: token in body only.
    r_body = _row(
        subject="Reminder: invoice {{INVOICE_NUMBER}}",
        body=("Hi — your outstanding balance of {{INVOICE_TOTAL}} is "
               "past due."),
    )
    # Row 3: token in BOTH.
    r_both = _row(
        subject="Outstanding balance {{INVOICE_TOTAL}}",
        body=("Hi — your outstanding balance of {{INVOICE_TOTAL}} is "
               "past due."),
    )
    db.marketing_templates.rows.extend([r_subj, r_body, r_both])

    out = _run(backfill_invoice_reminder_balance(
        db, tenant_id=TENANT_A, dry_run=False,
    ))

    assert out["totals"]["rows_rewritten"] == 3
    # Subject-only token.
    assert "{{INVOICE_BALANCE}}" in r_subj["subject"]
    assert "{{INVOICE_TOTAL}}" not in r_subj["subject"]
    # Body-only token.
    assert "{{INVOICE_BALANCE}}" in r_body["body"]
    assert "{{INVOICE_TOTAL}}" not in r_body["body"]
    # Both fields.
    assert "{{INVOICE_BALANCE}}" in r_both["subject"]
    assert "{{INVOICE_BALANCE}}" in r_both["body"]
    assert "{{INVOICE_TOTAL}}" not in r_both["subject"]
    assert "{{INVOICE_TOTAL}}" not in r_both["body"]


def test_sms_row_subject_none_stays_none():
    """SMS rows have ``subject=None``; the update path must not
    overwrite that with an empty string."""
    from migrations.backfill_invoice_reminder_balance_v1 import (
        backfill_invoice_reminder_balance,
    )
    db = _FakeDB()
    _seed_tenants(db, TENANT_A)
    row = _row(
        system_key="system_tpl_invoice_past_due_7d_sms",
        channel="sms",
        subject=None,
        body=("Reminder: your outstanding balance of {{INVOICE_TOTAL}} "
              "is past due.  Pay: {{PAY_LINK}}"),
    )
    db.marketing_templates.rows.append(row)

    _run(backfill_invoice_reminder_balance(
        db, tenant_id=TENANT_A, dry_run=False,
    ))

    assert row["subject"] is None
    assert "{{INVOICE_BALANCE}}" in row["body"]


def test_global_tenant_none_fallback_row_is_excluded_from_scope():
    """The ``invoice_reminder_email`` global fallback at
    ``tenant_id=None`` is excluded by the migration's match query —
    the shipped seed body already uses ``{{INVOICE_BALANCE}}`` post-
    Ticket-1, but belt-and-braces excludes it from scope even if a
    hypothetical operator somehow regressed the seed."""
    from migrations.backfill_invoice_reminder_balance_v1 import (
        backfill_invoice_reminder_balance,
    )
    db = _FakeDB()
    _seed_tenants(db, TENANT_A)
    # Hypothetical regressed global row — should NOT be touched.
    global_row = _row(
        tenant_id=None,
        system_key=None,
        code="invoice_reminder_email",
        body="Hi — your outstanding balance of {{INVOICE_TOTAL}} is past due.",
    )
    db.marketing_templates.rows.append(global_row)

    out = _run(backfill_invoice_reminder_balance(
        db, all_tenants=True, dry_run=False,
    ))

    assert out["totals"]["rows_rewritten"] == 0
    assert "{{INVOICE_TOTAL}}" in global_row["body"]
