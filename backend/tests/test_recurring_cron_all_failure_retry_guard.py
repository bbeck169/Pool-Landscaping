"""P2 #8 · Feb-2026 — RECURRING-ALL-FAILURE-RETRY-GUARD cron halt
guard regression suite.

Covers:

  1. Case 1 — min-sample BOUNDARY: 4-attempted/4-failed does NOT
     halt (below ``_HALT_MIN_SAMPLE``); 5-attempted/5-failed DOES
     halt (``all_fail`` rule, short-circuits remaining iteration).
  2. Case 2 — all-fail on an exactly-5-template batch halts with
     ``all_fail``.
  3. Case 3 — half-fail-large-batch on 10 templates (5 fail, 5
     pass) halts with ``half_fail_large_batch``.
  4. Case 4 — 4-of-8 failure (50% but batch size < 10) does NOT
     halt; cron completes.
  5. Case 5 — 8-of-20 failure (40%, below rate threshold) does
     NOT halt; cron completes.
  6. Case 6 — all-success batch does NOT halt, no audit row.
  7. Case 7 — mixed exception types aggregate per-class in
     ``failure_signatures`` with correct counts + sample ids.
  8. Case 8 — audit row payload shape: carries ``run_id``,
     ``trigger_rule``, per-tenant breakdown, and the
     ``failed_template_cursors_held`` precision invariant.

Design — uses pure async stubs (no HTTP, no live tenant, no K72
blocks). Patches:
  * ``db.recurring_job_templates.find`` → yields a controlled
    stream of fake template dicts.
  * ``_generate_from_template`` → monkeypatched to pass/raise per
    template-id driven by the test's ``fail_set``.
  * ``db.audit_logs.insert_one`` → captures writes to an in-memory
    list for assertion.

Follows the ``_FakeMongo``-style harness convention from
``tests/test_recurring_cron_cursor_fix.py``.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── Stubs ───────────────────────────────────────────────────────

class _TemplatesCursorStub:
    """Mimics the async-iterable Motor cursor returned by
    ``db.recurring_job_templates.find(...)``."""
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = list(docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


class _TemplatesCollectionStub:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs

    def find(self, *a, **kw):
        return _TemplatesCursorStub(self._docs)


class _AuditLogsStub:
    def __init__(self):
        self.inserted: List[Dict[str, Any]] = []

    async def insert_one(self, doc: Dict[str, Any]):
        self.inserted.append(doc)
        return None


def _mk_tpl(tid: str, tpl_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "id": tpl_id,
        "tenant_id": tid,
        "is_active": True,
    }
    base.update(overrides)
    return base


def _run_cron_with_fail_set(
    tpl_docs: List[Dict[str, Any]],
    fail_set: Dict[str, type],
) -> Dict[str, Any]:
    """Invoke ``run_recurring_job_generator`` with:
      * ``db.recurring_job_templates`` yielding ``tpl_docs`` in order
      * ``_generate_from_template`` raising ``fail_set[tpl_id]`` for
        matching ids; else returning ``{"inserted":1,"skipped":0}``
      * ``db.audit_logs.insert_one`` recorded into a stub

    Returns ``{"result": <cron return>, "audit": <AuditLogsStub>,
    "ensure_indexes_calls": int, "generate_calls": [tpl_id,...]}``."""
    from routers import recurring_jobs as rj
    from config import db as real_db

    tpls_stub = _TemplatesCollectionStub(tpl_docs)
    audit_stub = _AuditLogsStub()
    generate_calls: List[str] = []

    async def _fake_generate(tpl, through):
        tpl_id = tpl.get("id")
        generate_calls.append(tpl_id)
        exc_cls = fail_set.get(tpl_id)
        if exc_cls is not None:
            raise exc_cls(f"simulated {exc_cls.__name__} for {tpl_id}")
        return {"inserted": 1, "skipped": 0, "dates": []}

    # Preserve + swap the globals/attrs we're patching.
    orig_rjt = real_db.recurring_job_templates
    orig_audit = real_db.audit_logs
    orig_generate = rj._generate_from_template
    orig_ensure = rj._ensure_indexes

    ensure_calls = {"n": 0}
    async def _fake_ensure():
        ensure_calls["n"] += 1

    try:
        real_db.recurring_job_templates = tpls_stub
        real_db.audit_logs = audit_stub
        rj._generate_from_template = _fake_generate
        rj._ensure_indexes = _fake_ensure
        result = _run(rj.run_recurring_job_generator())
    finally:
        real_db.recurring_job_templates = orig_rjt
        real_db.audit_logs = orig_audit
        rj._generate_from_template = orig_generate
        rj._ensure_indexes = orig_ensure

    return {
        "result": result,
        "audit": audit_stub,
        "ensure_indexes_calls": ensure_calls["n"],
        "generate_calls": generate_calls,
    }


# ─── Case 1 · min-sample BOUNDARY ─────────────────────────────────

def test_min_sample_boundary_4_fail_no_halt_5_fail_halts():
    """Below ``_HALT_MIN_SAMPLE`` (5), even 100% failure does NOT
    halt — warmup cannot false-fire. At the 5th attempted/failed
    template, ``all_fail`` fires + short-circuits."""
    # Sub-test (a): 4 templates, all fail → no halt (completes).
    tpls_4 = [_mk_tpl("t-a", f"tpl-f{i}") for i in range(4)]
    fail_4 = {t["id"]: RuntimeError for t in tpls_4}
    r4 = _run_cron_with_fail_set(tpls_4, fail_4)
    assert r4["result"]["halted"] is False, (
        "4 attempted / 4 failed is below _HALT_MIN_SAMPLE=5; "
        f"got halted={r4['result']['halted']}"
    )
    assert r4["result"]["templates_failed"] == 4
    assert len(r4["audit"].inserted) == 0, "no audit row at <5 sample"

    # Sub-test (b): 5 templates, all fail → halt + short-circuit.
    # Include a 6th template to prove iteration stopped at #5.
    tpls_6 = [_mk_tpl("t-a", f"tpl-g{i}") for i in range(6)]
    fail_5 = {t["id"]: RuntimeError for t in tpls_6[:5]}
    r5 = _run_cron_with_fail_set(tpls_6, fail_5)
    assert r5["result"]["halted"] is True
    assert r5["result"]["halt_rule"] == "all_fail"
    assert r5["result"]["templates_attempted"] == 5, (
        "halt must short-circuit at the 5th template; "
        f"attempted={r5['result']['templates_attempted']}"
    )
    assert len(r5["generate_calls"]) == 5, "6th template must not be reached"
    assert len(r5["audit"].inserted) == 1


# ─── Case 2 · all-fail on an exactly-5-template batch ─────────────

def test_all_fail_on_exactly_5_batch_halts_all_fail():
    tpls = [_mk_tpl("t-b", f"tpl-h{i}") for i in range(5)]
    fail = {t["id"]: ValueError for t in tpls}
    r = _run_cron_with_fail_set(tpls, fail)
    assert r["result"]["halted"] is True
    assert r["result"]["halt_rule"] == "all_fail"
    assert r["result"]["templates_processed"] == 0


# ─── Case 3 · half-fail-large-batch on 10 ─────────────────────────

def test_half_fail_large_batch_halts_at_10_with_half_rule():
    """10 templates, odd indexes fail. By the 10th template:
    attempted=10, failed=5, rate=0.5 → half_fail_large_batch."""
    tpls = [_mk_tpl("t-c", f"tpl-i{i}") for i in range(10)]
    fail = {t["id"]: KeyError for i, t in enumerate(tpls) if i % 2 == 1}
    # Add a trailing 11th that must NOT be visited.
    tpls.append(_mk_tpl("t-c", "tpl-i-trailer"))
    r = _run_cron_with_fail_set(tpls, fail)
    assert r["result"]["halted"] is True
    assert r["result"]["halt_rule"] == "half_fail_large_batch"
    assert r["result"]["templates_attempted"] == 10
    assert "tpl-i-trailer" not in r["generate_calls"]


# ─── Case 4 · 4-of-8 failure (50% but batch < 10) → no halt ───────

def test_half_fail_small_batch_8_does_not_halt():
    tpls = [_mk_tpl("t-d", f"tpl-j{i}") for i in range(8)]
    # Fail the first 4 (worst-case: hits rate 1.0 at attempted=4 but
    # that's below min-sample; by attempted=8 the rate is 0.5 but
    # batch size 8 is below the half-rule threshold of 10).
    fail = {tpls[i]["id"]: RuntimeError for i in range(4)}
    r = _run_cron_with_fail_set(tpls, fail)
    assert r["result"]["halted"] is False, (
        "batch_size=8 is below _HALT_BATCH_SIZE_FOR_HALF_RULE=10; "
        f"got halt_rule={r['result']['halt_rule']}"
    )
    assert r["result"]["templates_attempted"] == 8
    assert r["result"]["templates_processed"] == 4
    assert r["result"]["templates_failed"] == 4


# ─── Case 5 · 8-of-20 failure (40%, below rate) → no halt ─────────

def test_below_rate_threshold_20_batch_8_fail_does_not_halt():
    tpls = [_mk_tpl("t-e", f"tpl-k{i}") for i in range(20)]
    # Distribute 8 failures across 20 so the running rate never
    # hits 0.5 at any checkpoint — final rate = 40%. Checkpoints:
    #   attempted=5  → 1 fail (20%)
    #   attempted=10 → 2 fail (20%)
    #   attempted=14 → 4 fail (28.6%)
    #   attempted=17 → 6 fail (35.3%)
    #   attempted=20 → 8 fail (40%)
    fail_indexes = [4, 7, 10, 13, 15, 16, 18, 19]
    fail_ids = {tpls[i]["id"]: RuntimeError for i in fail_indexes}
    r = _run_cron_with_fail_set(tpls, fail_ids)
    assert r["result"]["halted"] is False, (
        "40% failure rate (sparse) is below _HALT_HALF_RATE=0.5; "
        f"got halt_rule={r['result']['halt_rule']}"
    )
    assert r["result"]["templates_attempted"] == 20
    assert r["result"]["templates_failed"] == 8


# ─── Case 6 · all success → no halt, no audit row ─────────────────

def test_all_success_no_halt_no_audit_row():
    tpls = [_mk_tpl("t-f", f"tpl-m{i}") for i in range(15)]
    r = _run_cron_with_fail_set(tpls, fail_set={})
    assert r["result"]["halted"] is False
    assert r["result"]["halt_rule"] is None
    assert r["result"]["templates_processed"] == 15
    assert r["result"]["templates_failed"] == 0
    assert len(r["audit"].inserted) == 0


# ─── Case 7 · failure signature aggregation ───────────────────────

def test_failure_signatures_aggregate_by_exception_class():
    """5 templates, all fail — 3 with ValueError, 2 with KeyError.
    The audit row's ``failure_signatures`` list groups by exception
    class with correct counts + a sample template id per class."""
    tpls = [_mk_tpl("t-g", f"tpl-n{i}") for i in range(5)]
    fail = {
        tpls[0]["id"]: ValueError,
        tpls[1]["id"]: ValueError,
        tpls[2]["id"]: ValueError,
        tpls[3]["id"]: KeyError,
        tpls[4]["id"]: KeyError,
    }
    r = _run_cron_with_fail_set(tpls, fail)
    assert r["result"]["halted"] is True
    assert len(r["audit"].inserted) == 1
    sigs = {s["type"]: s for s in r["audit"].inserted[0]["payload"]["failure_signatures"]}
    assert "ValueError" in sigs
    assert "KeyError" in sigs
    assert sigs["ValueError"]["count"] == 3
    assert sigs["KeyError"]["count"] == 2
    assert sigs["ValueError"]["sample_template_id"] in {t["id"] for t in tpls[:3]}
    assert sigs["KeyError"]["sample_template_id"] in {t["id"] for t in tpls[3:]}


# ─── Case 8 · audit row payload shape (per-tenant halt) ──────────

def test_audit_row_payload_shape():
    """Pin the per-tenant audit row contract. Feb-2026 P0 refinement
    moved the halt from cross-tenant to per-tenant, so the audit
    row's ``tenant_id`` is now populated with the halting tenant
    (not ``None``), and the payload carries the new weekday-pivot
    forensics (``halted_weekday_counts`` +
    ``failure_signatures_by_weekday``) alongside the legacy
    ``failure_signatures`` flat list + ``failed_template_cursors_held``
    precision invariant.
    """
    tpls = [
        _mk_tpl("tenant-A", f"tpl-o{i}", day_of_week=i % 3)
        for i in range(5)
    ]
    fail = {t["id"]: RuntimeError for t in tpls}
    r = _run_cron_with_fail_set(tpls, fail)
    assert r["result"]["halted"] is True
    assert r["result"]["halt_rule"] == "all_fail"
    assert r["result"]["halted_tenants"] == ["tenant-A"]
    assert r["result"]["tenants_halted"] == 1
    rows = r["audit"].inserted
    # Per-tenant halt → one audit row for tenant-A.
    assert len(rows) == 1, (
        "per-tenant halt writes one audit row per halted tenant"
    )
    row = rows[0]

    # Top-level envelope. tenant_id is now the halting tenant (not
    # None) — this is the semantic difference between the legacy
    # cross-tenant halt audit and the Feb-2026 P0 per-tenant halt.
    assert row["action"] == "recurring_job.cron.batch_failure_halt"
    assert row["actor_user_id"] is None
    assert row["tenant_id"] == "tenant-A", (
        "per-tenant halt audit row carries the halting tenant_id"
    )
    assert "id" in row and row["id"]
    assert "created_at" in row and row["created_at"]

    # Payload — legacy fields preserved.
    p = row["payload"]
    assert p["run_id"] == r["result"]["run_id"]
    assert p["trigger_rule"] == "all_fail"
    assert p["tenant_id"] == "tenant-A"
    assert p["templates_attempted"] == 5
    assert p["templates_failed"] == 5
    assert p["templates_succeeded"] == 0
    # ``templates_by_tenant`` still folds every tenant visited this
    # run (only one in this fixture).
    assert set(p["templates_by_tenant"].keys()) == {"tenant-A"}
    assert p["templates_by_tenant"]["tenant-A"] == {
        "attempted": 5, "failed": 5,
    }
    # Flat failure_signatures preserved.
    sigs = {s["type"]: s for s in p["failure_signatures"]}
    assert "RuntimeError" in sigs
    assert sigs["RuntimeError"]["count"] == 5
    # New forensics — weekday pivot. String keys per BSON contract.
    # Weekdays 0, 1, 2 → counts (2, 2, 1) given day_of_week=i%3.
    assert set(p["halted_weekday_counts"].keys()) == {"0", "1", "2"}
    assert sum(p["halted_weekday_counts"].values()) == 5
    assert set(p["halted_weekday_failed_counts"].keys()) == {"0", "1", "2"}
    assert sum(p["halted_weekday_failed_counts"].values()) == 5
    # Per-weekday signature pivot — every weekday saw RuntimeError.
    for dow_key, by_exc in p["failure_signatures_by_weekday"].items():
        assert "RuntimeError" in by_exc
        assert by_exc["RuntimeError"] >= 1
    # Precision invariant per user ruling on Flag 4 wording.
    assert p["failed_template_cursors_held"] is True
