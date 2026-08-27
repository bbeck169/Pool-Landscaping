"""Feb-2026 · Crew Phase A · AquaTerra crew seed idempotency.

Covers ``scripts/seed_aquaterra_crews.py``:

* Fresh DB → seeds Blue Crew + Green Crew with 2 members each.
* Second run → no duplicates.
* Cross-tenant safety — other tenants are untouched.
"""
from __future__ import annotations

import asyncio

import pytest

from config import db


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestSeedAquaterraCrews:
    def test_seed_is_idempotent(self):
        """First run + second run leave identical crew set (by name)."""
        from scripts.seed_aquaterra_crews import seed_aquaterra_crews

        r1 = _run(seed_aquaterra_crews())
        if r1.get("reason") == "aquaterra_tenant_missing":
            pytest.skip("aquaterra tenant not seeded on this env")

        snap1 = _run(db.crews.count_documents(
            {"tenant_id": r1["tenant_id"]}))
        r2 = _run(seed_aquaterra_crews())
        snap2 = _run(db.crews.count_documents(
            {"tenant_id": r1["tenant_id"]}))

        # Same crew count after re-run.
        assert snap2 == snap1
        assert r2["ok"] is True
        # Crews expected by name (Blue + Green must be present).
        by_name = {c["name"]: c for c in _run(db.crews.find(
            {"tenant_id": r1["tenant_id"]}, {"_id": 0},
        ).to_list(20))}
        assert "Blue Crew" in by_name
        assert "Green Crew" in by_name

    def test_other_tenants_untouched(self):
        """Only AquaTerra gets crews from this seed — cross-tenant
        safety check. Other tenants' crew counts must be identical
        before + after."""
        from scripts.seed_aquaterra_crews import seed_aquaterra_crews

        before = {}
        for t in _run(db.tenants.find({"slug": {"$nin": ["aquaterra"]}},
                                            {"_id": 0, "id": 1, "slug": 1}).to_list(50)):
            before[t["id"]] = _run(
                db.crews.count_documents({"tenant_id": t["id"]}))

        _run(seed_aquaterra_crews())

        for tid, c in before.items():
            after = _run(
                db.crews.count_documents({"tenant_id": tid}))
            assert after == c, (
                f"tenant {tid} crew count changed from {c} to {after}"
            )
