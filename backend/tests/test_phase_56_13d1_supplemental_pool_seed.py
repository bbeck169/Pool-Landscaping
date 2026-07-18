"""Phase 56.13d1 · Supplemental Pool Training — seed integrity tests.

Runs against the .md drafts + dry-run seed script. Does NOT touch the
database (no --commit call). Guarantees the seed pipeline is loadable +
IP-safe + shape-valid at all times.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_SCRIPT = REPO_ROOT / "training_seed" / "seed_pool_supplemental.py"
CHAPTERS_ROOT = REPO_ROOT / "training_seed" / "training_pool_supplemental_chapters"

MODULES = [
    "module_a_filter_cleaning",
    "module_b_shaft_seal",
    "module_c_pump_priming",
    "module_d_jandy_orings",
    "module_e_vsp_programming",
]

MODULE_E = "module_e_vsp_programming"


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
    and b) contain no verbatim OEM manual phrases. Module E carries extra
    scrutiny — VSP programming content must NOT reproduce any OEM keypress
    sequence or menu-label pattern from Pentair or Hayward manuals."""

    BLACKLIST_UNIVERSAL = [
        "reproduced with permission",
        "copyright pentair",
        "copyright hayward",
        "copyright jandy",
        "© pentair",
        "© hayward",
        "© jandy",
    ]

    # Module E extra blacklist — verbatim OEM menu / keypress fingerprints.
    # Regex-based with word boundaries to avoid catching accidental
    # substrings ("full-speed 24/7" must NOT match "speed 2").
    BLACKLIST_MODULE_E_REGEX = [
        r"\bintellicenter\b",
        r"\bpush menu\b",
        r"\bpress menu\b",
        r"\bmenu then edit\b",
        r"\bmenu > edit\b",
        r"\bpress select\b",
        r"\bpress set\b",
        r"\bspeed [1-9]\b",
        r"\baux[1-9]\b",
        r"\barrow to schedule\b",
        r"\bpress start\b",
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
                for phrase in self.BLACKLIST_UNIVERSAL:
                    assert phrase not in text, \
                        f"universal IP-blacklist hit in {md.relative_to(REPO_ROOT)}: '{phrase}'"

    def test_module_e_no_oem_keypress_fingerprints(self):
        """Module E specifically must not contain any OEM keypad-menu
        fingerprint — no verbatim button sequences, no verbatim menu-item
        labels. Word-boundary regex to avoid false positives like
        'full-speed 24/7' matching 'speed 2'."""
        for md in (CHAPTERS_ROOT / MODULE_E).glob("*.md"):
            text = md.read_text(encoding="utf-8").lower()
            for pat in self.BLACKLIST_MODULE_E_REGEX:
                assert not re.search(pat, text), \
                    f"Module E IP-blacklist hit in {md.relative_to(REPO_ROOT)}: '{pat}'"

    def test_module_e_redirects_to_oem_manual(self):
        """Every Module E chapter must direct the reader to the OEM manual
        for exact keystrokes — this is the safety redirect that keeps our
        content concept-level while still practically useful."""
        for md in (CHAPTERS_ROOT / MODULE_E).glob("*.md"):
            text = md.read_text(encoding="utf-8").lower()
            assert "oem manual" in text, \
                f"Module E chapter missing 'OEM manual' redirect: {md.relative_to(REPO_ROOT)}"


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
        assert "Modules ready: 5" in result.stdout
        assert "Lessons:       35" in result.stdout
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
