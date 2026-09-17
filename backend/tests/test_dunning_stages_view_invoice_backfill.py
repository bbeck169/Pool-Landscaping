"""Feb 2026 · Invoice Email CTA Label ticket — Dunning stages backfill tests.

Covers the tester follow-up gap: existing tenants with persisted
``dunning_settings.stages`` continued sending the legacy "Pay online:"
copy until an admin hit ``reset-defaults``. The
``dunning_stages_view_invoice_backfill`` migration is the idempotent
ops-run remediation.

Test infrastructure follows the Feb 2026 baseline —
``httpx.ASGITransport`` isn't needed here because the migration is a
pure DB pass; we use ``@pytest.mark.anyio`` + a ``run_test`` helper
around a Motor-shaped in-memory stub so no preview Mongo state is
mutated.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import patch

import pytest


# ── Motor-shaped in-memory stub ─────────────────────────────────────
# Matches the minimum surface the migration touches:
#   db.dunning_settings.find(query, projection) → async cursor
#   db.dunning_settings.update_one(query, update)
class _AsyncCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        r = self._rows[self._i]
        self._i += 1
        return r


class _Coll:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.updates: List[Dict[str, Any]] = []

    def find(self, query=None, projection=None):
        # migration passes {} for query and a projection; stub ignores
        # the projection since the migration handles missing fields
        # tolerantly.
        return _AsyncCursor(self.rows)

    async def update_one(self, query, update):
        for r in self.rows:
            if r.get("tenant_id") == query.get("tenant_id"):
                # Apply $set + $push.
                if "$set" in update:
                    r.update(update["$set"])
                if "$push" in update:
                    for k, v in update["$push"].items():
                        r.setdefault(k, []).append(v)
                self.updates.append({"tenant_id": r.get("tenant_id"),
                                        "update": update})
                return


class _DB:
    def __init__(self, docs):
        self.dunning_settings = _Coll(docs)


# ── Fixtures ────────────────────────────────────────────────────────

def _legacy_body(stage_label: str) -> str:
    """Historical body_template shape — contains the ``Pay online:``
    literal that the migration should rewrite."""
    return (
        f"Hi {{customer_name}},\n\n"
        f"{stage_label}\n\n"
        f"Pay online: {{payment_link}}\n\n"
        f"Thanks,\n{{tenant_name}}"
    )


def _new_body(stage_label: str) -> str:
    return (
        f"Hi {{customer_name}},\n\n"
        f"{stage_label}\n\n"
        f"View invoice: {{payment_link}}\n\n"
        f"Thanks,\n{{tenant_name}}"
    )


def _seed_docs() -> List[Dict[str, Any]]:
    """Three tenants:
      * ``tenant-legacy``: 2 stages, both use the legacy "Pay online:"
        prefix → migration should rewrite both.
      * ``tenant-mixed``: 2 stages — 1 legacy, 1 custom-authored (no
        legacy prefix). Migration touches only the legacy one; the
        custom-authored stays byte-identical.
      * ``tenant-empty``: no persisted stages array. Migration must
        skip cleanly.
      * ``tenant-migrated``: already contains the new copy. Second
        run over the same DB is a no-op.
    """
    return [
        {
            "tenant_id": "tenant-legacy",
            "enabled": True,
            "stages": [
                {"id": "pre_due_3d", "body_template": _legacy_body("3-day heads-up")},
                {"id": "on_due_day", "body_template": _legacy_body("Due today")},
            ],
        },
        {
            "tenant_id": "tenant-mixed",
            "enabled": True,
            "stages": [
                {"id": "past_due_7d", "body_template": _legacy_body("7-day past due")},
                # Fully custom-authored — never contained the literal.
                {"id": "custom_dunning",
                 "body_template":
                     "Hi {customer_name}, please settle via bank transfer or "
                     "call {tenant_phone}. Ref {invoice_number}."},
            ],
        },
        {
            "tenant_id": "tenant-empty",
            "enabled": True,
            "stages": [],
        },
        {
            "tenant_id": "tenant-migrated",
            "enabled": True,
            "stages": [
                {"id": "pre_due_3d", "body_template": _new_body("3-day heads-up")},
            ],
        },
    ]


# ── Async runner (mirrors the Phase 41.1d anyio convention) ────────

def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _patch_db_stub(request):
    """Every test in this module gets its own fresh stub so the
    update side effects don't bleed across cases."""
    stub_db = _DB(_seed_docs())
    from services.migrations import dunning_stages_view_invoice_backfill as _mod
    with patch.object(_mod, "db", stub_db):
        request.node.stub_db = stub_db
        yield stub_db


# ═══════════════════════════════════════════════════════════════════
# 1 · Dry-run reports affected count without mutation
# ═══════════════════════════════════════════════════════════════════

def test_dry_run_reports_affected_but_does_not_mutate(request):
    from services.migrations.dunning_stages_view_invoice_backfill import (
        run_backfill,
    )
    stub = request.node.stub_db

    result = _run(run_backfill(dry_run=True))

    # tenant-legacy (2 stages) + tenant-mixed (1 stage) = 3 rewrites,
    # 2 tenants affected. tenant-empty + tenant-migrated skipped.
    assert result["dry_run"] is True
    assert result["tenants_scanned"] == 4
    assert result["tenants_affected"] == 2
    assert result["stages_rewritten"] == 3
    assert result["audit_stamped"] == 0

    # per_tenant order-agnostic assertion.
    ids = {p["tenant_id"] for p in result["per_tenant"]}
    assert ids == {"tenant-legacy", "tenant-mixed"}

    # DB untouched.
    assert stub.dunning_settings.updates == []
    # Bodies still contain the legacy literal on the legacy tenant.
    legacy = next(r for r in stub.dunning_settings.rows
                   if r["tenant_id"] == "tenant-legacy")
    for st in legacy["stages"]:
        assert "Pay online:" in st["body_template"]


# ═══════════════════════════════════════════════════════════════════
# 2 · Real-run flips old→new and is idempotent
# ═══════════════════════════════════════════════════════════════════

def test_real_run_flips_old_to_new_and_is_idempotent(request):
    from services.migrations.dunning_stages_view_invoice_backfill import (
        run_backfill, AUDIT_KEY,
    )
    stub = request.node.stub_db

    # First pass — writes.
    r1 = _run(run_backfill(dry_run=False))
    assert r1["dry_run"] is False
    assert r1["tenants_affected"] == 2
    assert r1["stages_rewritten"] == 3
    assert r1["audit_stamped"] == 2
    # DB reflects the rewrite.
    legacy = next(r for r in stub.dunning_settings.rows
                   if r["tenant_id"] == "tenant-legacy")
    for st in legacy["stages"]:
        assert "View invoice:" in st["body_template"]
        assert "Pay online:" not in st["body_template"]
    # Audit stamp landed on both affected tenants.
    audit_entries = [e for r in stub.dunning_settings.rows
                     for e in (r.get("audit_log") or [])
                     if e.get("key") == AUDIT_KEY]
    assert len(audit_entries) == 2
    assert all("at" in e for e in audit_entries)

    # Second pass — no-op. tenant-migrated (which we skipped on pass 1
    # because it was already in the new shape) STAYS skipped; the two
    # tenants we just migrated no longer contain the legacy prefix.
    r2 = _run(run_backfill(dry_run=False))
    assert r2["tenants_affected"] == 0
    assert r2["stages_rewritten"] == 0
    assert r2["audit_stamped"] == 0
    # No additional audit entries appended on the idempotent pass.
    audit_after = [e for r in stub.dunning_settings.rows
                   for e in (r.get("audit_log") or [])
                   if e.get("key") == AUDIT_KEY]
    assert len(audit_after) == 2


# ═══════════════════════════════════════════════════════════════════
# 3 · Tenants without persisted stages are ignored
# ═══════════════════════════════════════════════════════════════════

def test_tenant_without_persisted_stages_is_ignored(request):
    from services.migrations.dunning_stages_view_invoice_backfill import (
        run_backfill,
    )
    stub = request.node.stub_db

    _run(run_backfill(dry_run=False))

    empty = next(r for r in stub.dunning_settings.rows
                   if r["tenant_id"] == "tenant-empty")
    # No stages array bloat + no audit line stamped.
    assert empty["stages"] == []
    assert (empty.get("audit_log") or []) == []


# ═══════════════════════════════════════════════════════════════════
# 4 · Custom-authored stage bodies (no legacy literal) untouched
# ═══════════════════════════════════════════════════════════════════

def test_custom_authored_stage_bodies_are_untouched(request):
    from services.migrations.dunning_stages_view_invoice_backfill import (
        run_backfill,
    )
    stub = request.node.stub_db

    _run(run_backfill(dry_run=False))

    mixed = next(r for r in stub.dunning_settings.rows
                  if r["tenant_id"] == "tenant-mixed")
    custom = next(st for st in mixed["stages"]
                    if st["id"] == "custom_dunning")
    # Bank-transfer + call phone copy is preserved byte-for-byte.
    assert custom["body_template"] == (
        "Hi {customer_name}, please settle via bank transfer or "
        "call {tenant_phone}. Ref {invoice_number}."
    )


# ═══════════════════════════════════════════════════════════════════
# 5 · _rewrite_stage_body pure helper — unit-level guarantees
# ═══════════════════════════════════════════════════════════════════

def test_rewrite_stage_body_replaces_all_occurrences():
    """Some future stage body could conceivably reference the CTA
    twice; the helper handles that without a re.sub call."""
    from services.migrations.dunning_stages_view_invoice_backfill import (
        _rewrite_stage_body,
    )
    body = "Line 1 Pay online: A\nLine 2 Pay online: B"
    new, changed = _rewrite_stage_body(body)
    assert changed is True
    assert new == "Line 1 View invoice: A\nLine 2 View invoice: B"


def test_rewrite_stage_body_handles_empty_and_none():
    from services.migrations.dunning_stages_view_invoice_backfill import (
        _rewrite_stage_body,
    )
    for empty in ("", None):
        new, changed = _rewrite_stage_body(empty)
        assert changed is False
        assert new == empty
