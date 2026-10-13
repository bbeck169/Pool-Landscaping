"""P0 · Feb-2026 — Per-tenant halt + weekday-interleaved iteration
+ outer global safety net.

Pins the three structural refinements shipped alongside the
recurring-jobs cadence audit endpoint:

  1. ``_weekday_interleaved_order`` — iteration order visits at
     least one template per ``(tenant_id, day_of_week)`` cell
     before any cell is revisited.
  2. Per-tenant halt — a tenant halting does NOT halt other
     tenants' templates.
  3. Outer global safety net — ≥5 tenants halted OR
     ``total_attempted >= 50`` with ``>= 50%`` failure rate.
  4. Audit payload — new ``halted_weekday_counts`` +
     ``failure_signatures_by_weekday`` fields.
  5. Summary payload — new ``visited_weekday_counts``,
     ``materialized_by_weekday``, ``tenants_processed``,
     ``tenants_halted`` fields.

Uses the same ``_FakeMongo``-style harness convention as the
all-failure-retry-guard regression suite.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest


# ─── Stubs (duplicate the minimal harness here to keep tests
# self-contained + avoid cross-file import ordering surprises) ─────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _TemplatesCursorStub:
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


def _mk_tpl(tid: str, tpl_id: str, *, day_of_week: Any = None,
             **overrides: Any) -> Dict[str, Any]:
    base = {
        "id": tpl_id,
        "tenant_id": tid,
        "is_active": True,
        "day_of_week": day_of_week,
    }
    base.update(overrides)
    return base


def _run_cron(
    tpl_docs: List[Dict[str, Any]],
    fail_set: Dict[str, type],
) -> Dict[str, Any]:
    from routers import recurring_jobs as rj
    from config import db as real_db

    tpls_stub = _TemplatesCollectionStub(tpl_docs)
    audit_stub = _AuditLogsStub()
    generate_calls: List[Dict[str, Any]] = []

    async def _fake_generate(tpl, through):
        generate_calls.append({"id": tpl.get("id"),
                                 "tenant_id": tpl.get("tenant_id"),
                                 "day_of_week": tpl.get("day_of_week")})
        exc_cls = fail_set.get(tpl.get("id"))
        if exc_cls is not None:
            raise exc_cls(f"simulated {exc_cls.__name__} for {tpl.get('id')}")
        return {"inserted": 1, "skipped": 0, "dates": []}

    orig_rjt = real_db.recurring_job_templates
    orig_audit = real_db.audit_logs
    orig_generate = rj._generate_from_template
    orig_ensure = rj._ensure_indexes

    async def _fake_ensure():
        return None

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
        "generate_calls": generate_calls,
    }


# ─── §1 · Weekday-interleaved iteration ──────────────────────────

def test_weekday_interleaved_first_round_covers_all_weekdays_per_tenant():
    """20 templates: 2 tenants × 5 weekdays × 2 templates. First 10
    attempts across the batch must cover ≥4 distinct weekdays for
    at least one tenant — i.e. the interleave visits one weekday
    per round rather than clustering by weekday."""
    tpls: List[Dict[str, Any]] = []
    for tid in ("tenant-X", "tenant-Y"):
        for dow in range(5):
            for i in range(2):
                tpls.append(_mk_tpl(tid, f"{tid}-dow{dow}-n{i}",
                                       day_of_week=dow))
    r = _run_cron(tpls, fail_set={})
    assert r["result"]["templates_processed"] == 20
    # Collect the first 10 attempts per tenant and assert ≥4
    # distinct weekdays per tenant were visited in the first 10
    # overall attempts.
    first_ten = r["generate_calls"][:10]
    per_tenant_weekdays: Dict[str, set] = {}
    for c in first_ten:
        per_tenant_weekdays.setdefault(c["tenant_id"], set()).add(c["day_of_week"])
    assert len(per_tenant_weekdays) >= 1, (
        "first 10 attempts span at least one tenant"
    )
    # At least one tenant has >= 4 distinct weekdays visited in
    # the first 10 attempts — proves interleave is working, not
    # natural order (which would cluster day_of_week).
    assert any(len(wds) >= 4 for wds in per_tenant_weekdays.values()), (
        "no tenant covered >= 4 distinct weekdays in the first "
        f"10 attempts; got {per_tenant_weekdays}"
    )
    # Summary payload — new fields.
    _vwc = r["result"]["visited_weekday_counts"]
    assert set(_vwc.keys()) == {"0", "1", "2", "3", "4"}
    # 4 templates per weekday (2 tenants × 2 instances) across the
    # full run.
    for k in _vwc:
        assert _vwc[k] == 4


def test_weekday_interleave_deterministic_order():
    """Same fixture → same ordered iteration. No reliance on dict
    insertion-order flukes."""
    tpls = [
        _mk_tpl("t-A", "t-A-dow2-a", day_of_week=2),
        _mk_tpl("t-A", "t-A-dow0-a", day_of_week=0),
        _mk_tpl("t-A", "t-A-dow4-a", day_of_week=4),
        _mk_tpl("t-A", "t-A-dow0-b", day_of_week=0),
        _mk_tpl("t-A", "t-A-dow2-b", day_of_week=2),
    ]
    r1 = _run_cron(list(tpls), fail_set={})
    r2 = _run_cron(list(tpls), fail_set={})
    ids1 = [c["id"] for c in r1["generate_calls"]]
    ids2 = [c["id"] for c in r2["generate_calls"]]
    assert ids1 == ids2, (
        "weekday-interleave must be deterministic across runs; "
        f"got {ids1} vs {ids2}"
    )


# ─── §2 · Per-tenant halt — bad tenant doesn't starve good ───────

def test_per_tenant_halt_isolates_bad_tenant_from_healthy_tenant():
    """tenant-A has 5 broken templates, tenant-B has 10 healthy. The
    cron halts tenant-A only; tenant-B's 10 templates all process."""
    tpls = []
    for i in range(5):
        tpls.append(_mk_tpl("tenant-A", f"a{i}"))
    for i in range(10):
        tpls.append(_mk_tpl("tenant-B", f"b{i}"))
    fail = {f"a{i}": RuntimeError for i in range(5)}
    r = _run_cron(tpls, fail_set=fail)
    # tenant-A halts; tenant-B completes.
    assert r["result"]["halted"] is True
    assert "tenant-A" in r["result"]["halted_tenants"]
    assert "tenant-B" not in r["result"]["halted_tenants"]
    assert r["result"]["templates_failed"] == 5
    # All 10 tenant-B templates processed — no premature outer-loop
    # break.
    b_calls = [c for c in r["generate_calls"]
                if c["tenant_id"] == "tenant-B"]
    assert len(b_calls) == 10, (
        "tenant-B's healthy templates must all be processed even "
        f"after tenant-A halts; got {len(b_calls)}"
    )
    # Audit row — only tenant-A gets one.
    rows = r["audit"].inserted
    halt_rows = [r for r in rows
                   if r["action"] == "recurring_job.cron.batch_failure_halt"]
    assert len(halt_rows) == 1
    assert halt_rows[0]["tenant_id"] == "tenant-A"


def test_per_tenant_halt_rule_recorded_per_tenant():
    """Two bad tenants, two halts, two audit rows. ``halted_tenants``
    field surfaces both."""
    tpls = []
    for i in range(5):
        tpls.append(_mk_tpl("tenant-P", f"p{i}"))
    for i in range(5):
        tpls.append(_mk_tpl("tenant-Q", f"q{i}"))
    fail = {t["id"]: ValueError for t in tpls}
    r = _run_cron(tpls, fail_set=fail)
    assert set(r["result"]["halted_tenants"]) == {"tenant-P", "tenant-Q"}
    assert r["result"]["tenants_halted"] == 2
    # Two audit rows, one per halted tenant.
    halt_rows = [row for row in r["audit"].inserted
                   if row["action"] == "recurring_job.cron.batch_failure_halt"]
    assert len(halt_rows) == 2
    assert {row["tenant_id"] for row in halt_rows} == {
        "tenant-P", "tenant-Q",
    }
    for row in halt_rows:
        assert row["payload"]["trigger_rule"] == "all_fail"


# ─── §3 · Outer global safety net ────────────────────────────────

def test_global_halt_fires_at_5_halted_tenants_and_breaks_outer_loop():
    """6 tenants × 5 all-fail templates each. The weekday-interleave
    round-robin visits every tenant once per round, so by round 5
    all 6 tenants have been attempted 4 times each. During round 5
    the first 5 tenants (sorted ASC: A..E) hit their 5th all-fail
    attempt and per-tenant-halt one at a time. The moment E halts,
    ``halted_tenants`` reaches 5 → global halt fires → outer loop
    breaks BEFORE t-F's round-5 attempt. Net effect: t-F has 4
    visits (rounds 1-4), not 5."""
    tpls = []
    for tid in ("t-A", "t-B", "t-C", "t-D", "t-E", "t-F"):
        for i in range(5):
            tpls.append(_mk_tpl(tid, f"{tid}-{i}"))
    fail = {t["id"]: RuntimeError for t in tpls}
    r = _run_cron(tpls, fail_set=fail)
    # Global halt confirmed.
    assert r["result"]["halted"] is True
    assert r["result"]["global_halt_rule"] == "halted_tenants_threshold"
    # 5 tenants halted (A-E).
    halted = set(r["result"]["halted_tenants"])
    assert halted == {"t-A", "t-B", "t-C", "t-D", "t-E"}
    assert "t-F" not in halted
    # t-F partially visited (4 rounds) but NOT fully — proves the
    # global halt broke the outer loop before F's 5th attempt.
    f_calls = [c for c in r["generate_calls"] if c["tenant_id"] == "t-F"]
    assert len(f_calls) == 4, (
        "t-F must have 4 visits (rounds 1-4) before global halt "
        f"breaks the loop in round 5; got {len(f_calls)}"
    )
    # Audit rows: 5 per-tenant + 1 global.
    global_rows = [row for row in r["audit"].inserted
                     if row["action"] == "recurring_job.cron.global_batch_halt"]
    assert len(global_rows) == 1
    gp = global_rows[0]["payload"]
    assert gp["trigger_rule"] == "halted_tenants_threshold"
    assert gp["tenants_halted_count"] == 5
    assert set(gp["halted_tenants"]) == {
        "t-A", "t-B", "t-C", "t-D", "t-E",
    }


def test_global_halt_does_not_fire_under_tenant_threshold():
    """4 tenants halted + 1 healthy — global halt does NOT fire.
    Each tenant has its own audit row; the healthy tenant completes."""
    tpls = []
    for tid in ("t-A", "t-B", "t-C", "t-D"):
        for i in range(5):
            tpls.append(_mk_tpl(tid, f"{tid}-{i}"))
    # Healthy tenant with 5 passing templates — gives per-tenant
    # halt a chance to NOT fire for it.
    for i in range(5):
        tpls.append(_mk_tpl("t-OK", f"ok-{i}"))
    fail = {t["id"]: RuntimeError for t in tpls if not t["id"].startswith("ok-")}
    r = _run_cron(tpls, fail_set=fail)
    assert r["result"]["halted"] is True, (
        "per-tenant halts still mark the run as halted"
    )
    assert r["result"]["global_halt_rule"] is None, (
        "global halt must not fire at 4 halted tenants"
    )
    assert set(r["result"]["halted_tenants"]) == {
        "t-A", "t-B", "t-C", "t-D",
    }
    # Healthy tenant processes all 5.
    ok_calls = [c for c in r["generate_calls"]
                  if c["tenant_id"] == "t-OK"]
    assert len(ok_calls) == 5


# ─── §4 · Audit payload shape (new fields) ────────────────────────

def test_per_tenant_halt_audit_payload_has_new_weekday_pivots():
    """Audit row carries ``halted_weekday_counts`` +
    ``halted_weekday_failed_counts`` + ``failure_signatures_by_weekday``
    with string keys (BSON contract) matching the halting tenant's
    attempted/failed weekday distribution."""
    tpls = [
        _mk_tpl("tenant-A", "a-wed-0", day_of_week=2),
        _mk_tpl("tenant-A", "a-wed-1", day_of_week=2),
        _mk_tpl("tenant-A", "a-thu-0", day_of_week=3),
        _mk_tpl("tenant-A", "a-thu-1", day_of_week=3),
        _mk_tpl("tenant-A", "a-fri-0", day_of_week=4),
    ]
    fail = {
        "a-wed-0": RuntimeError, "a-wed-1": RuntimeError,
        "a-thu-0": KeyError, "a-thu-1": KeyError,
        "a-fri-0": ValueError,
    }
    r = _run_cron(tpls, fail_set=fail)
    rows = r["audit"].inserted
    halt_rows = [row for row in rows
                   if row["action"] == "recurring_job.cron.batch_failure_halt"]
    assert len(halt_rows) == 1
    p = halt_rows[0]["payload"]
    # Weekday counts — Wed, Thu, Fri each attempted ≥ 1.
    assert set(p["halted_weekday_counts"].keys()) >= {"2", "3", "4"}
    assert p["halted_weekday_counts"]["2"] == 2
    assert p["halted_weekday_counts"]["3"] == 2
    assert p["halted_weekday_counts"]["4"] == 1
    # Same for failed counts.
    assert p["halted_weekday_failed_counts"]["2"] == 2
    assert p["halted_weekday_failed_counts"]["3"] == 2
    assert p["halted_weekday_failed_counts"]["4"] == 1
    # Signature pivot by weekday.
    sbw = p["failure_signatures_by_weekday"]
    assert sbw["2"]["RuntimeError"] == 2
    assert sbw["3"]["KeyError"] == 2
    assert sbw["4"]["ValueError"] == 1


# ─── §5 · Summary payload shape (new fields) ──────────────────────

def test_summary_payload_has_new_counts():
    """``result`` carries ``visited_weekday_counts``,
    ``materialized_by_weekday``, ``tenants_processed``,
    ``tenants_halted``, ``halted_tenants``."""
    tpls = [
        _mk_tpl("tenant-A", f"a-{i}", day_of_week=i % 3)
        for i in range(3)
    ] + [
        _mk_tpl("tenant-B", f"b-{i}", day_of_week=i % 3)
        for i in range(3)
    ]
    r = _run_cron(tpls, fail_set={})
    res = r["result"]
    for k in ("visited_weekday_counts", "materialized_by_weekday",
              "tenants_processed", "tenants_halted",
              "halted_tenants", "halted_tenant_rules",
              "global_halt_rule"):
        assert k in res, f"summary missing new field: {k}"
    assert res["tenants_processed"] == 2
    assert res["tenants_halted"] == 0
    assert res["halted_tenants"] == []
    assert res["global_halt_rule"] is None
    # visited + materialized agree — each attempt produced 1
    # inserted job in the stub.
    assert res["visited_weekday_counts"] == res["materialized_by_weekday"]
    # 2 templates per weekday across tenants A+B.
    assert sum(res["visited_weekday_counts"].values()) == 6
