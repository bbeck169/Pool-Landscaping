"""TD-86 · Feb-2026 — cleanup script predicate tests.

Covers the pure-function predicates used by
``backend/scripts/cleanup_crew_cross_tenant_tech_ids.py`` — the
async DB-touching driver is exercised by the live preview
``--dry-run`` invocation, so this suite focuses on the two
pure helpers that gate the categorisation:

  * ``categorise_bad_ids`` — foreign_tenant vs orphan counters
    on a per-crew ``bad_ids`` list.
  * ``render_summary`` — markdown shape (counters, dry-run vs
    apply banner, per-tenant table).

The driver's idempotency is enforced structurally: a re-run
after ``--apply`` finds zero drift because the prune UPDATE
rewrites ``tech_ids`` + ``member_added_at`` to the clean set.
That contract is locked by the live dry-run smoke check and
the FE/BE regression suites.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(
    "/app/backend/scripts/cleanup_crew_cross_tenant_tech_ids.py",
)


@pytest.fixture(scope="module")
def cleanup_mod():
    spec = importlib.util.spec_from_file_location(
        "td86_cleanup", SCRIPT_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ═════════════════════════════════════════════════════════════
# categorise_bad_ids
# ═════════════════════════════════════════════════════════════

def test_categorise_all_orphan(cleanup_mod):
    out = cleanup_mod.categorise_bad_ids(
        ["ghost1", "ghost2", "ghost3"], foreign_lookup={},
    )
    assert out == {"foreign_tenant": 0, "orphan": 3}


def test_categorise_all_foreign_tenant(cleanup_mod):
    out = cleanup_mod.categorise_bad_ids(
        ["u1", "u2"],
        foreign_lookup={"u1": "t2", "u2": "t3"},
    )
    assert out == {"foreign_tenant": 2, "orphan": 0}


def test_categorise_mixed(cleanup_mod):
    out = cleanup_mod.categorise_bad_ids(
        ["u1", "ghost", "u2", "ghost2"],
        foreign_lookup={"u1": "t2", "u2": "t3"},
    )
    assert out == {"foreign_tenant": 2, "orphan": 2}


def test_categorise_empty(cleanup_mod):
    out = cleanup_mod.categorise_bad_ids([], foreign_lookup={})
    assert out == {"foreign_tenant": 0, "orphan": 0}


# ═════════════════════════════════════════════════════════════
# render_summary
# ═════════════════════════════════════════════════════════════

def _mk_result(apply, totals_overrides=None, per_tenant=None,
                 tenant_filter=None):
    base_totals = {
        "crews_scanned": 0,
        "crews_with_drift": 0,
        "tech_ids_pruned_orphan": 0,
        "tech_ids_pruned_foreign_tenant": 0,
        "member_added_at_entries_pruned": 0,
        "crews_updated": 0,
        "crews_failed_with_reason": [],
    }
    base_totals.update(totals_overrides or {})
    return {
        "apply": apply,
        "tenant_filter": tenant_filter,
        "totals": base_totals,
        "per_tenant": per_tenant or {},
    }


def test_render_summary_dry_run_banner(cleanup_mod):
    md = cleanup_mod.render_summary(_mk_result(apply=False))
    assert "DRY-RUN (read-only)" in md
    assert "no writes — dry-run" in md


def test_render_summary_apply_banner(cleanup_mod):
    md = cleanup_mod.render_summary(_mk_result(
        apply=True,
        totals_overrides={"crews_updated": 2},
    ))
    assert "APPLY (writes)" in md
    assert "writes applied" in md


def test_render_summary_counters_appear(cleanup_mod):
    md = cleanup_mod.render_summary(_mk_result(
        apply=False,
        totals_overrides={
            "crews_scanned": 2,
            "crews_with_drift": 2,
            "tech_ids_pruned_orphan": 4,
            "tech_ids_pruned_foreign_tenant": 1,
            "member_added_at_entries_pruned": 3,
        },
    ))
    assert "crews_scanned: **2**" in md
    assert "crews_with_drift: **2**" in md
    assert "tech_ids_pruned_orphan: **4**" in md
    assert "tech_ids_pruned_foreign_tenant: **1**" in md
    assert "member_added_at_entries_pruned: **3**" in md


def test_render_summary_per_tenant_block(cleanup_mod):
    md = cleanup_mod.render_summary(_mk_result(
        apply=False,
        per_tenant={
            "t-alpha": {
                "name": "Alpha Co",
                "crews_scanned": 3,
                "crews_with_drift": 1,
                "tech_ids_pruned_orphan": 2,
                "tech_ids_pruned_foreign_tenant": 0,
                "member_added_at_entries_pruned": 2,
                "crews_updated": 0,
                "crews_failed": [],
            },
        },
    ))
    assert "### `t-alpha` (Alpha Co)" in md
    assert "crews_scanned: 3" in md
    assert "crews_with_drift: 1" in md


def test_render_summary_tenant_filter_scope(cleanup_mod):
    md = cleanup_mod.render_summary(_mk_result(
        apply=False, tenant_filter="t-scoped",
    ))
    assert "single tenant `t-scoped`" in md


def test_render_summary_empty_per_tenant_prints_sentinel(cleanup_mod):
    md = cleanup_mod.render_summary(_mk_result(apply=False))
    assert "_No crews with drift found._" in md


# ═════════════════════════════════════════════════════════════
# Script surface — CLI help contract
# ═════════════════════════════════════════════════════════════

def test_script_file_exposes_dry_run_default_and_apply_flag():
    """TD-86 regression lock — the operator-approved spec requires
    dry-run default + ``--apply`` opt-in + ``--tenant <id>`` scope.
    """
    src = SCRIPT_PATH.read_text()
    assert '"--apply"' in src
    assert '"--tenant"' in src
    assert "action=\"store_true\"" in src
    assert "Default is dry-run" in src


def test_script_prunes_member_added_at_in_lockstep():
    """TD-86 audit §7 — the sister-map must be pruned alongside
    tech_ids so the two shapes on each crew doc stay consistent."""
    src = SCRIPT_PATH.read_text()
    assert '"member_added_at": mem_added' in src
    assert "member_added_at_entries_pruned" in src
