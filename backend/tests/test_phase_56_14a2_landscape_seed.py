"""Phase 56.14a2 · Landscape Training — Modules 4-7 seed integrity tests.

Mirrors ``test_phase_56_14a1_landscape_seed.py`` shape but targets the four
Feb-2026 modules committed to the DB:

- ``landscape-pavers-hardscape``       (Module 4 — Pavers & Hardscape)
- ``landscape-turf-sod``               (Module 5 — Turf & Sod)
- ``landscape-outdoor-kitchen``        (Module 6 — Outdoor Kitchen)
- ``landscape-valve-diagnostics``      (Module 7 — Valve Diagnostics)

The suite proves:
- Draft directories exist with the expected chapter counts.
- Every draft chapter carries the in-house authorship disclaimer.
- Every draft chapter is clean under the IP-safety blacklist.
- Every quiz has at least 10 well-formed questions.
- The four modules are present in the database with the expected chapter
  and quiz counts (proves the ``--commit`` step landed the payload).
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env")

from training_seed.seed_common import run_blacklist_scan  # noqa: E402

CHAPTERS_ROOT = REPO_ROOT / "training_seed" / "training_landscape_chapters"

MODULE_SPEC = [
    # (dir_name, module_code, expected_chapter_count, expected_min_quiz_qs)
    ("module_4_pavers",             "landscape-pavers-hardscape",    5, 10),
    ("module_5_turf_sod",           "landscape-turf-sod",            5, 10),
    ("module_6_outdoor_kitchen",    "landscape-outdoor-kitchen",     4, 10),
    ("module_7_valve_diagnostics",  "landscape-valve-diagnostics",   4, 10),
]

DISCLAIMER_TOKEN = "original in-house authorship"


class TestDraftShape:
    @pytest.mark.parametrize("dir_name,code,chapters,min_qs", MODULE_SPEC)
    def test_module_directory_exists(self, dir_name, code, chapters, min_qs):
        assert (CHAPTERS_ROOT / dir_name).is_dir(), f"missing draft dir: {dir_name}"

    @pytest.mark.parametrize("dir_name,code,chapters,min_qs", MODULE_SPEC)
    def test_module_has_expected_chapter_count(self, dir_name, code, chapters, min_qs):
        mds = sorted((CHAPTERS_ROOT / dir_name).glob("*.md"))
        assert len(mds) == chapters, \
            f"{dir_name}: {len(mds)} chapters found, expected {chapters}"

    @pytest.mark.parametrize("dir_name,code,chapters,min_qs", MODULE_SPEC)
    def test_module_has_quiz_json_with_min_questions(self, dir_name, code, chapters, min_qs):
        quiz_path = CHAPTERS_ROOT / dir_name / "quiz.json"
        assert quiz_path.exists(), f"{dir_name}: quiz.json missing"
        data = json.loads(quiz_path.read_text(encoding="utf-8"))
        qs = data.get("questions", [])
        assert len(qs) >= min_qs, \
            f"{dir_name}: {len(qs)} quiz questions, expected >= {min_qs}"
        for i, q in enumerate(qs):
            assert set(q.keys()) >= {"q", "choices", "answer"}, \
                f"{dir_name} Q{i}: missing required keys"
            assert isinstance(q["choices"], list) and len(q["choices"]) >= 2, \
                f"{dir_name} Q{i}: choices malformed"
            assert isinstance(q["answer"], int) and 0 <= q["answer"] < len(q["choices"]), \
                f"{dir_name} Q{i}: answer index out of range"


class TestIPSafety:
    @pytest.mark.parametrize("dir_name,code,chapters,min_qs", MODULE_SPEC)
    def test_every_chapter_has_disclaimer(self, dir_name, code, chapters, min_qs):
        for md in sorted((CHAPTERS_ROOT / dir_name).glob("*.md")):
            assert DISCLAIMER_TOKEN in md.read_text(encoding="utf-8").lower(), \
                f"{md.relative_to(CHAPTERS_ROOT)} missing '{DISCLAIMER_TOKEN}' disclaimer"

    @pytest.mark.parametrize("dir_name,code,chapters,min_qs", MODULE_SPEC)
    def test_every_chapter_is_blacklist_clean(self, dir_name, code, chapters, min_qs):
        for md in sorted((CHAPTERS_ROOT / dir_name).glob("*.md")):
            hits = run_blacklist_scan(md.read_text(encoding="utf-8"))
            assert not hits, f"{md.relative_to(CHAPTERS_ROOT)} tripped blacklist: {hits}"


class TestDBCommit:
    @pytest.fixture(scope="class")
    def db_modules(self):
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        async def _fetch():
            out = {}
            for _dir, code, _c, _q in MODULE_SPEC:
                doc = await db.training_modules.find_one(
                    {"code": code, "is_system": True}, {"_id": 0})
                out[code] = doc
            return out
        results = asyncio.run(_fetch())
        client.close()
        return results

    @pytest.mark.parametrize("dir_name,code,chapters,min_qs", MODULE_SPEC)
    def test_module_present_in_db(self, dir_name, code, chapters, min_qs, db_modules):
        assert db_modules[code] is not None, \
            f"{code} was not committed to db.training_modules"

    @pytest.mark.parametrize("dir_name,code,chapters,min_qs", MODULE_SPEC)
    def test_db_lesson_count_matches_drafts(self, dir_name, code, chapters, min_qs, db_modules):
        doc = db_modules[code]
        assert doc is not None
        assert len(doc.get("lessons") or []) == chapters, \
            f"{code}: DB has {len(doc.get('lessons') or [])} lessons, expected {chapters}"

    @pytest.mark.parametrize("dir_name,code,chapters,min_qs", MODULE_SPEC)
    def test_db_quiz_count_matches_drafts(self, dir_name, code, chapters, min_qs, db_modules):
        doc = db_modules[code]
        assert doc is not None
        qs = (doc.get("quiz") or {}).get("questions") or []
        assert len(qs) >= min_qs, \
            f"{code}: DB has {len(qs)} quiz questions, expected >= {min_qs}"

    def test_total_landscape_modules_in_db_is_seven(self, db_modules):
        # 3 pre-existing (56.14a1) + 4 new (56.14a2) = 7 total system landscape modules.
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        async def _count():
            return await db.training_modules.count_documents(
                {"department": "landscaping", "is_system": True})
        total = asyncio.run(_count())
        client.close()
        assert total == 7, f"expected 7 system landscape modules, got {total}"
