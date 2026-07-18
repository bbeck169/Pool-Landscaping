"""Phase 56.13d1 · Supplemental Pool Training — seed integrity tests.

Runs against the .md drafts + dry-run seed script. Does NOT touch the
database (no --commit call). Guarantees the seed pipeline is loadable +
IP-safe + shape-valid at all times.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_SCRIPT = REPO_ROOT / "training_seed" / "seed_pool_supplemental.py"
CHAPTERS_ROOT = REPO_ROOT / "training_seed" / "training_pool_supplemental_chapters"

MODULES = ["module_a_filter_cleaning", "module_b_shaft_seal", "module_c_pump_priming"]


class TestSeedShape:
    def test_all_three_modules_exist(self):
        for m in MODULES:
            assert (CHAPTERS_ROOT / m).is_dir(), f"missing module dir: {m}"

    def test_each_module_has_seven_chapters(self):
        for m in MODULES:
            md_files = sorted((CHAPTERS_ROOT / m).glob("*.md"))
            assert len(md_files) == 7, f"{m} has {len(md_files)} chapters, expected 7"

    def test_each_module_has_quiz(self):
        for m in MODULES:
            quiz = CHAPTERS_ROOT / m / "quiz.json"
            assert quiz.exists(), f"missing quiz for {m}"
            data = json.loads(quiz.read_text())
            assert "questions" in data
            assert len(data["questions"]) >= 8, f"{m} quiz has {len(data['questions'])} Qs, expected ≥8"
            for i, q in enumerate(data["questions"]):
                assert set(q.keys()) >= {"q", "choices", "answer"}, f"{m} Q{i} missing keys"
                assert isinstance(q["choices"], list) and len(q["choices"]) == 4
                assert 0 <= q["answer"] < 4


class TestIPSafety:
    """Every chapter body must a) carry the in-house authorship disclaimer,
    and b) contain no verbatim OEM manual phrases."""

    BLACKLIST = [
        "reproduced with permission",
        "copyright pentair",
        "copyright hayward",
        "copyright jandy",
        "© pentair",
        "© hayward",
        "© jandy",
    ]

    def test_disclaimer_present(self):
        for m in MODULES:
            for md in (CHAPTERS_ROOT / m).glob("*.md"):
                text = md.read_text(encoding="utf-8").lower()
                assert "original in-house authorship" in text, \
                    f"disclaimer missing in {md.relative_to(REPO_ROOT)}"

    def test_no_blacklisted_phrases(self):
        for m in MODULES:
            for md in (CHAPTERS_ROOT / m).glob("*.md"):
                text = md.read_text(encoding="utf-8").lower()
                for phrase in self.BLACKLIST:
                    assert phrase not in text, \
                        f"IP-blacklist hit in {md.relative_to(REPO_ROOT)}: {phrase}"


class TestSeedScriptDryRun:
    def test_dry_run_completes(self):
        """The seed script must run to completion in --dry-run mode
        (no --commit) without touching the DB and print a summary."""
        result = subprocess.run(
            [sys.executable, str(SEED_SCRIPT)],
            capture_output=True, text=True, timeout=30,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"dry-run failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        assert "Modules ready: 3" in result.stdout
        assert "Lessons:       21" in result.stdout
        assert "DRY-RUN — no database writes" in result.stdout

    def test_no_commit_flag_leak(self):
        """Sanity: bare invocation must NOT contain the word 'Committing'.
        Protects against a future accidental default flip."""
        result = subprocess.run(
            [sys.executable, str(SEED_SCRIPT)],
            capture_output=True, text=True, timeout=30,
            cwd=str(REPO_ROOT),
        )
        assert "Committing to Mongo" not in result.stdout


class TestQuizAnswers:
    """Each quiz answer_index must select a real choice; every choice list
    must contain 4 non-empty entries."""

    def test_answers_index_range(self):
        for m in MODULES:
            data = json.loads((CHAPTERS_ROOT / m / "quiz.json").read_text())
            for i, q in enumerate(data["questions"]):
                assert 0 <= q["answer"] < len(q["choices"]), f"{m} Q{i}: bad answer index"
                for c in q["choices"]:
                    assert isinstance(c, str) and c.strip(), f"{m} Q{i}: empty choice"
