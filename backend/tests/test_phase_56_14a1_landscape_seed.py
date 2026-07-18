"""Phase 56.14a1 · Landscape Training — seed integrity tests.

Mirrors test_phase_56_13d1_supplemental_pool_seed.py structure.
Does NOT hit the DB; guarantees the seed pipeline is loadable + IP-safe.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_SCRIPT = REPO_ROOT / "training_seed" / "seed_landscape.py"
CHAPTERS_ROOT = REPO_ROOT / "training_seed" / "training_landscape_chapters"

MODULES = [
    "module_1_irrigation_repairs",
    "module_2_irrigation_timers",
    "module_3_small_engine",
]

MODULE_2 = "module_2_irrigation_timers"


class TestSeedShape:
    def test_all_three_modules_exist(self):
        for m in MODULES:
            assert (CHAPTERS_ROOT / m).is_dir(), f"missing module dir: {m}"

    def test_each_module_has_seven_chapters(self):
        for m in MODULES:
            md = sorted((CHAPTERS_ROOT / m).glob("*.md"))
            assert len(md) == 7, f"{m}: {len(md)} chapters, expected 7"

    def test_each_module_has_quiz(self):
        for m in MODULES:
            quiz = CHAPTERS_ROOT / m / "quiz.json"
            assert quiz.exists()
            data = json.loads(quiz.read_text())
            assert len(data["questions"]) >= 8
            for i, q in enumerate(data["questions"]):
                assert set(q.keys()) >= {"q", "choices", "answer"}, f"{m} Q{i}: missing keys"
                assert isinstance(q["choices"], list) and len(q["choices"]) == 4
                assert 0 <= q["answer"] < 4


class TestIPSafety:
    UNIVERSAL_BL = [
        "reproduced with permission",
        "copyright hunter", "copyright rain bird", "copyright toro",
        "copyright honda", "copyright briggs",
        "© hunter", "© rain bird", "© toro", "© honda", "© briggs",
    ]

    # Module 2 — controller menu fingerprints.
    MODULE_2_REGEX = [
        r"\bpush prg\b",
        r"\bpress prg\b",
        r"\bstation [1-9]\b",
        r"\bprogram [abc]\b",
        r"\brotary switch\b",
    ]

    def test_disclaimer_present(self):
        for m in MODULES:
            for md in (CHAPTERS_ROOT / m).glob("*.md"):
                text = md.read_text(encoding="utf-8").lower()
                assert "original in-house authorship" in text, \
                    f"disclaimer missing in {md.relative_to(REPO_ROOT)}"

    def test_no_universal_blacklist_hits(self):
        for m in MODULES:
            for md in (CHAPTERS_ROOT / m).glob("*.md"):
                text = md.read_text(encoding="utf-8").lower()
                for phrase in self.UNIVERSAL_BL:
                    assert phrase not in text, \
                        f"universal IP-blacklist hit in {md.relative_to(REPO_ROOT)}: '{phrase}'"

    def test_module_2_no_menu_fingerprints(self):
        """Module 2 chapters must not contain OEM controller menu / keypress
        fingerprints. Word-boundary regex so 'programs A, B, C' as prose
        doesn't match, but 'Program A' as an OEM menu label does."""
        for md in (CHAPTERS_ROOT / MODULE_2).glob("*.md"):
            text = md.read_text(encoding="utf-8").lower()
            for pat in self.MODULE_2_REGEX:
                assert not re.search(pat, text), \
                    f"Module 2 IP-blacklist hit in {md.relative_to(REPO_ROOT)}: '{pat}'"

    def test_module_2_redirects_to_oem_manual(self):
        for md in (CHAPTERS_ROOT / MODULE_2).glob("*.md"):
            text = md.read_text(encoding="utf-8").lower()
            assert "oem manual" in text, \
                f"Module 2 chapter missing 'OEM manual' redirect: {md.relative_to(REPO_ROOT)}"


class TestSeedScriptDryRun:
    def test_dry_run_completes(self):
        result = subprocess.run(
            [sys.executable, str(SEED_SCRIPT)],
            capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"dry-run failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        assert "Modules ready:" in result.stdout
        # Phase 4 · Batch B added drafts for modules 4-7; total is now 7.
        assert "landscape-irrigation-repairs" in result.stdout
        assert "landscape-irrigation-timers" in result.stdout
        assert "landscape-small-engine" in result.stdout
        assert "Lessons:" in result.stdout
        assert "DRY-RUN — no database writes" in result.stdout

    def test_no_commit_flag_leak(self):
        result = subprocess.run(
            [sys.executable, str(SEED_SCRIPT)],
            capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT),
        )
        assert "Committing to Mongo" not in result.stdout


class TestQuizAnswers:
    def test_answers_index_range(self):
        for m in MODULES:
            data = json.loads((CHAPTERS_ROOT / m / "quiz.json").read_text())
            for i, q in enumerate(data["questions"]):
                assert 0 <= q["answer"] < len(q["choices"]), f"{m} Q{i}: bad answer index"
                for c in q["choices"]:
                    assert isinstance(c, str) and c.strip(), f"{m} Q{i}: empty choice"
