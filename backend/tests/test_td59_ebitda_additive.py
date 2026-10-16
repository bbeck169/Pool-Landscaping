"""TD-59 · Feb-2026 — EBITDA soft-add on the EBIT report backend.

Phase 7 Commit 1 of the EBIT→EBITDA ship (Option 3: deprecate EBIT,
add EBITDA as the headline).

Formula confirmation (locked in-code at services/finance/ebit.py):
    ebit   = revenue - cogs - opex - depreciation - labor_cost_total
    ebitda = ebit + depreciation

where ``depreciation`` already bundles both the ``depreciation`` AND
``amortization`` expense categories (``DEPRECIATION_CATEGORIES`` on
``services/finance/ebit.py``). Therefore no separate amortization
math is required — adding the single ``depreciation`` term back is
sufficient.

Covers (10 cases):

Live compute math (3) — exercised against a seeded tenant so the
real ``compute_ebit`` pipeline (checks loader, LLM override map,
labor compute, recurring-labor compute) runs end-to-end:
    1. ``compute_ebit`` returns an ``ebitda`` field.
    2. ``ebitda == ebit + depreciation`` (within rounding).
    3. ``apply_edits`` returns an ``ebitda`` reflecting the applied
       edits (not stale).

Snapshot persistence + lazy fill (4):
    4. ``_hydrate_ebitda`` fills missing field on legacy docs.
    5. ``_hydrate_ebitda`` is non-destructive on already-filled docs.
    6. ``_hydrate_ebitda`` hydrates the embedded ``computed_live``.
    7. ``_hydrate_ebitda`` tolerates None + empty-dict input.

Path aliases + backward-compat (3):
    8. ``/reports/ebit`` + ``/reports/ebitda`` are registered.
    9. Both aliases delegate to ``ebit_compute``.
   10. Backward-compat — every pre-TD-59 field remains in the
       ``compute_ebit`` response (additive, not replace).
"""
from __future__ import annotations

import asyncio
import inspect
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

from services.finance.ebit import apply_edits, compute_ebit
from routers import ebit as ebit_router_mod
from routers.ebit import _hydrate_ebitda


_ENV = dotenv_values(Path("/app/backend/.env"))
_TENANT = f"td59-tenant-{uuid.uuid4().hex[:8]}"


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _sync_db():
    from pymongo import MongoClient
    return MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]


def _cleanup():
    for coll in ("checks", "invoices", "payments", "jobs", "pool_jobs",
                   "users", "recurring_labor_costs", "quotes",
                   "timecards", "timesheet_entries",
                   "expense_categories"):
        _sync_db()[coll].delete_many({"tenant_id": _TENANT})


def _seed_tenant_with_dep_and_amort():
    """Seed a tenant with one depreciation check ($500) + one
    amortization check ($300) + one opex check ($1000). Running
    ``compute_ebit`` should surface ``depreciation=800`` (both
    categories bundle) and ``ebitda = ebit + 800``."""
    _cleanup()
    _sync_db().checks.insert_many([
        {"id": "c-dep", "tenant_id": _TENANT, "amount": 500,
         "category": "depreciation",
         "check_number": f"td59-dep-{uuid.uuid4().hex[:6]}",
         "bank_account_id": "td59-bank",
         "date": "2026-01-15",
         "voided_at": None},
        {"id": "c-amort", "tenant_id": _TENANT, "amount": 300,
         "category": "amortization",
         "check_number": f"td59-amort-{uuid.uuid4().hex[:6]}",
         "bank_account_id": "td59-bank",
         "date": "2026-01-20",
         "voided_at": None},
        {"id": "c-opex", "tenant_id": _TENANT, "amount": 1000,
         "category": "office",
         "check_number": f"td59-opex-{uuid.uuid4().hex[:6]}",
         "bank_account_id": "td59-bank",
         "date": "2026-01-10",
         "voided_at": None},
    ])


def _compute_live():
    from config import db
    return _run(compute_ebit(
        db, _TENANT, "2026-01-01", "2026-01-31", "cash",
    ))


# ──────────────────────────────────────────────────────────────────
# 1–3. Live compute math
# ──────────────────────────────────────────────────────────────────
def test_compute_ebit_returns_ebitda_field():
    _seed_tenant_with_dep_and_amort()
    try:
        out = _compute_live()
        assert "ebitda" in out, (
            "compute_ebit response must include an ``ebitda`` field "
            "(TD-59 additive wire shape)."
        )
    finally:
        _cleanup()


def test_ebitda_equals_ebit_plus_depreciation():
    _seed_tenant_with_dep_and_amort()
    try:
        out = _compute_live()
        # depreciation sums depreciation + amortization categories.
        assert out["depreciation"] == 800.0, (
            f"Expected depreciation to bundle depreciation+amortization "
            f"(500+300=800); got {out['depreciation']}"
        )
        # Core TD-59 math identity.
        diff = out["ebitda"] - (out["ebit"] + out["depreciation"])
        assert abs(diff) < 0.01, (
            f"ebitda={out['ebitda']} ebit={out['ebit']} "
            f"depreciation={out['depreciation']}; expected "
            f"ebitda == ebit + depreciation (within rounding)."
        )
        # EBITDA is strictly HIGHER than EBIT by exactly D+A.
        assert round(out["ebitda"] - out["ebit"], 2) == 800.0
    finally:
        _cleanup()


def test_apply_edits_returns_ebitda_reflecting_changes():
    _seed_tenant_with_dep_and_amort()
    try:
        base = _compute_live()
        # Nudge opex up by $200 via adjustments.
        edited = apply_edits(base, {"opex": 200}, None)
        # Adjustment flows: new ebit = base ebit - 200; new ebitda
        # also = base ebitda - 200 (depreciation unchanged).
        assert round(edited["ebit"] - base["ebit"], 2) == -200.0
        assert round(edited["ebitda"] - base["ebitda"], 2) == -200.0
        # Invariant: ebitda - ebit must still equal depreciation.
        assert round(
            edited["ebitda"] - edited["ebit"], 2,
        ) == edited["depreciation"]
    finally:
        _cleanup()


# ──────────────────────────────────────────────────────────────────
# 4–7. Snapshot persistence + lazy fill (pure helper, no DB)
# ──────────────────────────────────────────────────────────────────
def test_hydrate_ebitda_fills_missing_field_on_legacy_doc():
    legacy = {
        "id": "snap-legacy",
        "revenue": 10_000, "cogs": 3_000, "opex": 2_500,
        "depreciation": 800, "ebit": 3_000,
        # No ``ebitda`` key — pre-TD-59 shape.
    }
    out = _hydrate_ebitda(dict(legacy))
    assert out["ebitda"] == 3_800.0  # 3_000 + 800


def test_hydrate_ebitda_is_non_destructive_on_already_filled_doc():
    doc = {
        "ebit": 1_000, "depreciation": 400,
        "ebitda": 9_999,  # intentionally weird — must survive
    }
    out = _hydrate_ebitda(dict(doc))
    assert out["ebitda"] == 9_999


def test_hydrate_ebitda_hydrates_computed_live_subdoc():
    legacy = {
        "id": "snap-legacy",
        "ebit": 1_200, "depreciation": 300,
        "computed_live": {
            "revenue": 10_000, "cogs": 3_000, "opex": 2_500,
            "depreciation": 300, "ebit": 1_200,
        },
    }
    out = _hydrate_ebitda(dict(legacy))
    assert out["ebitda"] == 1_500.0
    assert out["computed_live"]["ebitda"] == 1_500.0


def test_hydrate_ebitda_tolerates_none_and_empty():
    # None short-circuits (falsy guard).
    assert _hydrate_ebitda(None) is None
    # Empty dict is also falsy — short-circuits unchanged. The
    # read-path callers only invoke the hydrator on documents that
    # survived a Mongo find; empty-dict inputs are a defensive guard,
    # not a hot path.
    assert _hydrate_ebitda({}) == {}


# ──────────────────────────────────────────────────────────────────
# 8–10. Path aliases + backward-compat
# ──────────────────────────────────────────────────────────────────
def test_reports_ebit_and_ebitda_aliases_registered():
    paths = {r.path for r in ebit_router_mod.router.routes
                if hasattr(r, "path")}
    assert "/reports/ebit" in paths, (
        "TD-59 must register the /reports/ebit alias."
    )
    assert "/reports/ebitda" in paths, (
        "TD-59 must register the /reports/ebitda alias."
    )
    # Historical /ebit/compute endpoint stays intact.
    assert "/ebit/compute" in paths


def test_reports_aliases_delegate_to_ebit_compute():
    src_a = inspect.getsource(ebit_router_mod.report_ebit_alias)
    src_b = inspect.getsource(ebit_router_mod.report_ebitda_alias)
    for src in (src_a, src_b):
        assert "ebit_compute(" in src, (
            "alias must delegate to ebit_compute to guarantee "
            "payload parity between /reports/* and /ebit/compute"
        )


def test_backward_compat_ebit_compute_shape_additive_only():
    """Every pre-TD-59 field on the ``compute_ebit`` response remains
    present. ``ebitda`` is additive, not a replace."""
    _seed_tenant_with_dep_and_amort()
    try:
        out = _compute_live()
        for k in ("range_from", "range_to", "revenue_basis",
                    "revenue", "cogs", "opex", "depreciation", "ebit",
                    "labor_cost", "recurring_labor_cost",
                    "labor_cost_total", "breakdown"):
            assert k in out, (
                f"TD-59 must not drop pre-existing field {k!r} "
                f"from the compute_ebit response (backward-compat gate)."
            )
        # New field is additive, not a rename.
        assert "ebitda" in out
    finally:
        _cleanup()
