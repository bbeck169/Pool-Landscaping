"""Phase 56.13a — CPO seed integrity tests.

These tests validate the assembled seed payload WITHOUT touching the
database (i.e., they exercise `seed_cpo_module(dry_run=True)`). They are
the guardrails that:

- Every quiz question has exactly ONE `correct_choice_ids` entry.
- Module badge label is "CPO Prep — Completed" and never contains
  "CPO Certified" (avoids implying certification).
- The IP-safety disclaimer string is present verbatim on the module doc.
- Every chapter body is >= 400 and <= 1200 words.
- SHA-256 of each chapter body is logged in the test output for spot-check
  visibility (no verbatim external content, no accidental reuse).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


# Make `backend.seed.training_cpo` importable without requiring a full
# backend package (server.py does not need to import cleanly for these
# integrity tests).
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Import via the `training_seed` package for consistency with the run command.
from training_seed import training_cpo as tcpo  # noqa: E402


@pytest.fixture(scope="module")
def summary():
    """Run the seed in dry_run mode. Uses asyncio because the function is
    async in order to share signature with the commit path."""
    return asyncio.get_event_loop().run_until_complete(tcpo.seed_cpo_module(dry_run=True)) \
        if sys.version_info < (3, 10) else asyncio.run(tcpo.seed_cpo_module(dry_run=True))


@pytest.fixture(scope="module")
def payload():
    return tcpo.build_module_payload()


class TestQuizIntegrity:
    def test_every_question_has_exactly_one_correct_choice(self, payload):
        questions = payload["quiz"]["questions"]
        assert questions, "quiz must have questions"
        for q in questions:
            cc = q.get("correct_choice_ids") or []
            assert isinstance(cc, list), f"{q.get('id')} correct_choice_ids must be list"
            assert len(cc) == 1, \
                f"{q.get('id')} must have EXACTLY 1 correct_choice_ids entry, got {cc!r}"
            choices = q.get("choices") or []
            choice_ids = {c["id"] for c in choices}
            assert cc[0] in choice_ids, \
                f"{q.get('id')} correct_choice_ids {cc!r} not in choices {choice_ids!r}"

    def test_question_count_at_least_50(self, payload):
        assert len(payload["quiz"]["questions"]) >= 50, \
            "CPO prep must ship at least 50 practice questions"

    def test_passing_score_is_75_percent(self, payload):
        assert abs(payload["quiz"]["passing_score"] - 0.75) < 1e-6


class TestBadgeAndDisclaimer:
    def test_badge_label_is_prep_completed(self, payload):
        assert payload["badge_label"] == "CPO Prep — Completed"

    def test_badge_label_never_says_certified(self, payload):
        # Case-insensitive substring guard; blocks any future edit that
        # would imply the badge is an official certification.
        assert "cpo certified" not in payload["badge_label"].lower()

    def test_disclaimer_present_verbatim(self, payload):
        expected = ("This is prep material only. Official CPO certification "
                    "requires enrollment with an authorized provider (PHTA / NSPF).")
        assert payload["disclaimer"] == expected


class TestChapterWordCounts:
    def test_every_chapter_within_bounds(self, payload):
        MIN, MAX = tcpo.MIN_CHAPTER_WORDS, tcpo.MAX_CHAPTER_WORDS
        for lesson in payload["lessons"]:
            wc = lesson["word_count"]
            assert MIN <= wc <= MAX, \
                f"{lesson['id']} word_count {wc} outside {MIN}-{MAX} range"

    def test_exactly_nine_chapters(self, payload):
        assert len(payload["lessons"]) == 9, \
            "CPO prep must ship all 9 chapters"


class TestSpotCheckShas:
    """Log the sha256 of each chapter body so the user can spot-check for
    accidental reuse across seed runs. This test is intentionally soft — it
    logs and passes; a future run that reproduces a suspicious sha would
    be caught by manual review."""

    def test_log_chapter_shas(self, summary, capsys):
        assert "chapter_sha256" in summary
        print("\n[CPO SEED INTEGRITY] chapter sha256 map:")
        for chid, sha in summary["chapter_sha256"].items():
            print(f"  {chid}: {sha}")
        # Sanity check: no duplicates between chapters.
        shas = list(summary["chapter_sha256"].values())
        assert len(shas) == len(set(shas)), \
            "two chapters produced identical sha256 — that indicates accidental duplication"


class TestDryRunDoesNotCommit:
    def test_summary_reports_committed_false(self, summary):
        assert summary["committed"] is False, \
            "dry_run=True must NEVER report committed=True"

    def test_summary_reports_is_system_true(self, summary):
        assert summary["is_system"] is True, \
            "CPO seed must be marked as a system module"
