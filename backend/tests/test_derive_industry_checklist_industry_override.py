"""Phase D3 · Feb 2026 — checklist_industry override-key parity.

D2 shipped ``job.checklist_industry`` as an alternate explicit
override signal on the web deriver. D3 brings backend
``derive_industry_for_job`` into parity so both keys are honoured
identically.

Priority chain post-D3:
  1. ``job.checklist_industry`` (Phase D3 · new)
  2. ``job.industry``            (Phase MI1 · existing)
  3. keyword scan
  4. tenant primary industry
  5. ``"pool"`` fallback

An INVALID ``checklist_industry`` (non-canonical slug) does NOT
error — the function falls through to ``industry`` (and onward).
"""
from __future__ import annotations

from routers.industry_checklists import derive_industry_for_job


def test_checklist_industry_wins_over_service_type_keyword():
    """``job.checklist_industry`` beats a keyword-match on
    ``service_type`` — the override key exists precisely for the
    "dispatcher classified this job by hand" case."""
    got = derive_industry_for_job(
        {"checklist_industry": "roofing",
         "service_type": "Window Cleaning residential"},
        None,
    )
    assert got == "roofing", got


def test_checklist_industry_wins_over_conflicting_industry_field():
    """When both ``checklist_industry`` and ``industry`` are set,
    the newer D3 override key wins so a client that promoted its
    tenant-level ``industry`` to a per-job override doesn't clobber
    the dispatcher's manual classification."""
    got = derive_industry_for_job(
        {"checklist_industry": "plumbing",
         "industry": "solar",
         "service_type": "Solar Panel Cleaning"},
        None,
    )
    assert got == "plumbing", got


def test_invalid_checklist_industry_falls_through_to_industry():
    """Non-canonical ``checklist_industry`` must NOT raise. The
    function falls through to ``industry`` (and, failing that, the
    keyword scan / tenant / pool fallback) so a stale client can't
    poison the deriver by shipping a bad override slug."""
    # ``industry`` is valid → honoured after checklist_industry
    # falls through.
    got = derive_industry_for_job(
        {"checklist_industry": "unicorn_rides",
         "industry": "hvac",
         "service_type": "Window Cleaning"},
        None,
    )
    assert got == "hvac", got
    # Both override keys invalid → keyword scan wins.
    got2 = derive_industry_for_job(
        {"checklist_industry": "unicorn_rides",
         "industry": "nope",
         "service_type": "Window Cleaning residential"},
        None,
    )
    assert got2 == "window_cleaning", got2
