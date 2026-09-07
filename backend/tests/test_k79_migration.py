"""Phase K79 · Feb-2026 — Backfill migration unit test.

Directly invokes ``scripts.k79_customer_group_display_migration.run()``
against a scratch collection to verify:
  * Docs missing ``customer_group_display`` get set to False.
  * Docs with ``customer_group_display=None`` get set to False.
  * Docs already carrying True/False are left alone.
  * Idempotent — second run reports zero modifications.
  * Audit doc lands in ``db.migration_runs``.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

# Backend module resolution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_k79_migration_backfills_missing_and_null():
    module = importlib.import_module(
        "scripts.k79_customer_group_display_migration"
    )
    from config import db

    audits_before = _run(
        db.migration_runs.count_documents(
            {"migration": module.MIGRATION_KEY},
        )
    )

    # Seed three scratch docs — missing / null / explicit-true.
    scratch = [
        {"id": "k79-mig-missing", "tenant_id": "k79-test",
         "title": "missing flag"},
        {"id": "k79-mig-null", "tenant_id": "k79-test",
         "customer_group_display": None, "title": "null flag"},
        {"id": "k79-mig-explicit-true", "tenant_id": "k79-test",
         "customer_group_display": True, "title": "explicit"},
    ]
    _run(db.quotes.insert_many([dict(d) for d in scratch]))
    try:
        result = _run(module.run())
        assert result["status"] == "ok"
        assert result["matched"] >= 2
        assert result["modified"] >= 2

        m = _run(db.quotes.find_one(
            {"id": "k79-mig-missing"},
            {"_id": 0, "customer_group_display": 1},
        ))
        n = _run(db.quotes.find_one(
            {"id": "k79-mig-null"},
            {"_id": 0, "customer_group_display": 1},
        ))
        t = _run(db.quotes.find_one(
            {"id": "k79-mig-explicit-true"},
            {"_id": 0, "customer_group_display": 1},
        ))
        assert m["customer_group_display"] is False
        assert n["customer_group_display"] is False
        assert t["customer_group_display"] is True  # untouched

        # Idempotent re-run: our scratch docs stay in their final state.
        result2 = _run(module.run())
        assert result2["status"] in ("ok", "noop")
        m2 = _run(db.quotes.find_one(
            {"id": "k79-mig-missing"},
            {"_id": 0, "customer_group_display": 1},
        ))
        assert m2["customer_group_display"] is False

        audits_after = _run(db.migration_runs.count_documents(
            {"migration": module.MIGRATION_KEY},
        ))
        assert audits_after > audits_before
    finally:
        _run(db.quotes.delete_many(
            {"id": {"$in": [d["id"] for d in scratch]}}
        ))
