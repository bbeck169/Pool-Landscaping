"""TD-72 · Feb-2026 — Imported-invoice title migration unit tests.

Pins the 5-branch contract operator ruled:
  (A) line_items[0] wins when present
  (B) notes wins when no line items (trimmed + truncated to 120)
  (C) Service — MM/DD/YYYY fallback when neither line items nor
      notes are populated
  (D) non-matching title → untouched (regression lock)
  (E) already-migrated row → idempotent (zero-write re-run)

Also covers:
  * flag-gating — a title that matches the regex but has NO
    imported flag is NEVER rewritten (operator-ruled "do not
    rewrite coincidental matches").
  * multi-tenant guard — ``--tenant`` scope filters correctly.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from scripts.migrate_imported_invoice_titles import (
    is_imported_placeholder_title,
    resolve_imported_title,
    migrate,
)


# ═══════════════════════════════════════════════════════════════════
# Minimal Mongo stub — just enough surface for the migration driver.
# ═══════════════════════════════════════════════════════════════════
class _Collection:
    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = rows  # By-reference so writes land back

    def _match(self, doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
        for k, v in query.items():
            if k == "$or":
                if not any(self._match(doc, sub) for sub in v):
                    return False
                continue
            if k == "$not":
                raise NotImplementedError
            if isinstance(v, dict):
                rv = doc.get(k)
                if "$regex" in v:
                    import re as _re
                    flags = _re.IGNORECASE if "i" in v.get("$options", "") else 0
                    if rv is None or not _re.search(v["$regex"], str(rv), flags):
                        return False
                    continue
                if "$exists" in v:
                    present = k in doc
                    if present != v["$exists"]:
                        return False
                if "$ne" in v and doc.get(k) == v["$ne"]:
                    return False
                if "$not" in v:
                    inner = v["$not"]
                    if "$regex" in inner:
                        import re as _re
                        flags = _re.IGNORECASE if "i" in inner.get("$options", "") else 0
                        rv2 = doc.get(k)
                        if rv2 is not None and _re.search(inner["$regex"], str(rv2), flags):
                            return False
                continue
            if doc.get(k) != v:
                return False
        return True

    def find(self, query: Dict[str, Any] = None, _projection: Dict[str, Any] = None):
        q = query or {}
        matched = [r for r in self.rows if self._match(r, q)]

        class _Cur:
            def __init__(self, items):
                self._items = items
                self._i = 0
            def __aiter__(self):
                return self
            async def __anext__(self):
                if self._i >= len(self._items):
                    raise StopAsyncIteration
                r = self._items[self._i]
                self._i += 1
                return r
        return _Cur(matched)

    async def count_documents(self, query: Dict[str, Any]) -> int:
        return sum(1 for r in self.rows if self._match(r, query))

    async def update_one(self, filt: Dict[str, Any], update: Dict[str, Any]):
        for i, r in enumerate(self.rows):
            if self._match(r, filt):
                set_dict = update.get("$set") or {}
                self.rows[i] = {**r, **set_dict}

                class _Res:
                    modified_count = 1
                return _Res()

        class _Res:
            modified_count = 0
        return _Res()


class _DB:
    def __init__(self, invoices: List[Dict[str, Any]]):
        self.quotes = _Collection(invoices)


# ═══════════════════════════════════════════════════════════════════
# 1 · is_imported_placeholder_title predicate.
# ═══════════════════════════════════════════════════════════════════
class TestPredicate:
    def test_matches_canonical(self):
        assert is_imported_placeholder_title({"title": "Import #259"}) is True

    def test_matches_whitespace_and_case_variants(self):
        assert is_imported_placeholder_title({"title": "  Import #  259  "}) is True
        assert is_imported_placeholder_title({"title": "import #259"}) is True
        assert is_imported_placeholder_title({"title": "IMPORT#259"}) is True

    def test_rejects_legitimate_titles(self):
        # The regex is anchored start-to-end so partial matches
        # on legitimate titles don't trigger.
        assert is_imported_placeholder_title({"title": "Imported pool chemicals"}) is False
        assert is_imported_placeholder_title({"title": "Pool service Import #259"}) is False
        assert is_imported_placeholder_title({"title": "Weekly service"}) is False

    def test_null_safe(self):
        assert is_imported_placeholder_title({}) is False
        assert is_imported_placeholder_title({"title": None}) is False
        assert is_imported_placeholder_title({"title": ""}) is False


# ═══════════════════════════════════════════════════════════════════
# 2 · resolve_imported_title — 5 operator-spec branches.
# ═══════════════════════════════════════════════════════════════════
class TestResolveImportedTitle:

    def _imported(self, **extra) -> Dict[str, Any]:
        return {"title": "Import #259", **extra}

    def test_branch_a_line_item_description_wins(self):
        """Branch (A) · line_items[0] wins when present."""
        inv = self._imported(
            line_items=[{"description": "Weekly landscape maintenance"}],
            notes="Billed per contract",
            created_at="2025-03-14T12:00:00Z",
        )
        new_title, branch = resolve_imported_title(inv)
        assert new_title == "Weekly landscape maintenance"
        assert branch == "line_item"

    def test_branch_a_line_item_title_as_alias(self):
        inv = self._imported(line_items=[{"title": "Pool chemistry — March"}])
        new_title, branch = resolve_imported_title(inv)
        assert new_title == "Pool chemistry — March"
        assert branch == "line_item"

    def test_branch_b_notes_when_no_line_items(self):
        """Branch (B) · notes wins when no line items."""
        inv = self._imported(notes="  Billed per contract  ")
        new_title, branch = resolve_imported_title(inv)
        assert new_title == "Billed per contract"
        assert branch == "notes"

    def test_branch_b_notes_truncated_to_120_with_ellipsis(self):
        long = "A" * 150
        inv = self._imported(notes=long)
        new_title, branch = resolve_imported_title(inv)
        assert new_title == "A" * 120 + "\u2026"
        assert branch == "notes"

    def test_branch_c_service_fallback_date_from_created_at(self):
        """Branch (C) · Service — MM/DD/YYYY fallback."""
        inv = self._imported(created_at="2025-03-14T12:00:00Z")
        new_title, branch = resolve_imported_title(inv)
        assert new_title == "Service — 03/14/2025"
        assert branch == "fallback"

    def test_branch_c_service_fallback_date_from_invoice_date(self):
        inv = self._imported(invoice_date="2024-11-05T00:00:00Z")
        new_title, branch = resolve_imported_title(inv)
        assert new_title == "Service — 11/05/2024"

    def test_branch_c_service_fallback_date_from_datetime(self):
        inv = self._imported(created_at=datetime(2025, 3, 14, 12, 0, tzinfo=timezone.utc))
        new_title, branch = resolve_imported_title(inv)
        assert new_title == "Service — 03/14/2025"

    def test_branch_c_edge_case_no_usable_date(self):
        inv = self._imported()
        new_title, branch = resolve_imported_title(inv)
        assert new_title == "Service"
        assert branch == "fallback"


# ═══════════════════════════════════════════════════════════════════
# 3 · migrate driver — dry-run + apply + idempotency + flag gate.
# ═══════════════════════════════════════════════════════════════════
class TestMigrate:

    def _seed(self) -> List[Dict[str, Any]]:
        """Five invoices covering every branch of the operator spec:
          (a) imported + has line items
          (b) imported + no line items, has notes
          (c) imported + no line items, no notes, has created_at (fallback)
          (d) imported-shaped title but NO imported flag — must NOT be rewritten
          (e) non-matching title — must NOT be rewritten (idempotency anchor)
          (f) already-migrated row — regular title, imported flag present (idempotency)
        """
        return [
            # (a) line_item branch
            {
                "_id": "a1", "id": "a1",
                "doc_type": "invoice", "tenant_id": "T1",
                "title": "Import #100", "source": "import",
                "line_items": [{"description": "Weekly landscape maintenance"}],
                "notes": "ignored", "created_at": "2025-01-01T00:00:00Z",
            },
            # (b) notes branch
            {
                "_id": "b1", "id": "b1",
                "doc_type": "invoice", "tenant_id": "T1",
                "title": "Import #101", "import_batch_id": "B1",
                "line_items": [],
                "notes": "Billed per contract",
                "created_at": "2025-02-02T00:00:00Z",
            },
            # (c) fallback branch
            {
                "_id": "c1", "id": "c1",
                "doc_type": "invoice", "tenant_id": "T2",
                "title": "Import #102", "import_number": "102",
                "line_items": [], "notes": "",
                "created_at": "2025-03-14T12:00:00Z",
            },
            # (d) imported-shaped title WITHOUT imported flag — must be left alone
            {
                "_id": "d1", "id": "d1",
                "doc_type": "invoice", "tenant_id": "T1",
                "title": "Import #999",  # no source/import_batch_id/import_number
                "line_items": [{"description": "Would-be rewrite"}],
                "created_at": "2025-04-04T00:00:00Z",
            },
            # (e) non-matching title (regression lock — never touched)
            {
                "_id": "e1", "id": "e1",
                "doc_type": "invoice", "tenant_id": "T1",
                "title": "Weekly service · March 14",
                "source": "import",  # imported but title is fine
                "line_items": [{"description": "Would-be rewrite"}],
            },
            # (f) already-migrated (title replaced on a prior run)
            {
                "_id": "f1", "id": "f1",
                "doc_type": "invoice", "tenant_id": "T1",
                "title": "Weekly landscape maintenance",
                "source": "import",
                "line_items": [{"description": "Weekly landscape maintenance"}],
            },
        ]

    def test_dry_run_matches_abc_leaves_everything_untouched(self):
        """Dry-run reports 3 matches but writes nothing."""
        rows = self._seed()
        snapshot = copy.deepcopy(rows)
        db = _DB(rows)
        report = asyncio.run(migrate(db, apply=False))
        assert report["mode"] == "dry-run"
        assert report["matched"] == 3  # (a) (b) (c) — (d) excluded by flag
        assert report["updated"] == 0
        assert report["updated_by_branch"] == {
            "line_item": 1, "notes": 1, "fallback": 1,
        }
        # Not a single row touched.
        assert rows == snapshot

    def test_apply_rewrites_abc_only_leaves_d_e_f_untouched(self):
        """Apply rewrites the 3 matching rows; the 3 others (d/e/f)
        are untouched → operator-ruled "do not rewrite coincidental
        matches" + "non-imported titles unchanged" invariants."""
        rows = self._seed()
        db = _DB(rows)
        report = asyncio.run(migrate(db, apply=True))
        assert report["mode"] == "apply"
        assert report["matched"] == 3
        assert report["updated"] == 3
        assert report["failed_count"] == 0
        assert report["updated_by_branch"] == {
            "line_item": 1, "notes": 1, "fallback": 1,
        }
        # Verify each rewrite surfaced the right branch.
        by_id = {r["id"]: r for r in rows}
        assert by_id["a1"]["title"] == "Weekly landscape maintenance"
        assert by_id["b1"]["title"] == "Billed per contract"
        assert by_id["c1"]["title"] == "Service — 03/14/2025"
        # (d) — imported-shaped title but no flag — untouched.
        assert by_id["d1"]["title"] == "Import #999"
        # (e) — non-matching title — untouched.
        assert by_id["e1"]["title"] == "Weekly service · March 14"
        # (f) — already-migrated — untouched.
        assert by_id["f1"]["title"] == "Weekly landscape maintenance"

    def test_rerun_after_apply_is_a_no_op(self):
        """Second ``apply`` finds 0 matches — idempotent."""
        rows = self._seed()
        db = _DB(rows)
        asyncio.run(migrate(db, apply=True))  # first apply
        # Snapshot after first apply, then re-run — nothing changes.
        snapshot = copy.deepcopy(rows)
        report = asyncio.run(migrate(db, apply=True))
        assert report["matched"] == 0
        assert report["updated"] == 0
        assert report["updated_by_branch"] == {
            "line_item": 0, "notes": 0, "fallback": 0,
        }
        assert rows == snapshot

    def test_tenant_scope_filters_correctly(self):
        """``--tenant T2`` touches only (c), skips (a) + (b) + (e) + (f)."""
        rows = self._seed()
        db = _DB(rows)
        report = asyncio.run(migrate(db, apply=True, tenant="T2"))
        assert report["matched"] == 1
        assert report["updated"] == 1
        assert report["updated_by_branch"]["fallback"] == 1
        by_id = {r["id"]: r for r in rows}
        assert by_id["c1"]["title"] == "Service — 03/14/2025"
        # Other tenants untouched.
        assert by_id["a1"]["title"] == "Import #100"
        assert by_id["b1"]["title"] == "Import #101"
