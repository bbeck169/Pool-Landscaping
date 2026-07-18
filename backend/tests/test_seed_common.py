"""Phase 4 · Batch B / D4 — Tests for the shared seed_common module."""
from __future__ import annotations
import re, sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from training_seed.seed_common import (  # noqa: E402
    run_blacklist_scan, DEFAULT_BLACKLIST,
    load_chapter_markdown, build_quiz_questions,
)


class TestBlacklist:
    def test_default_patterns_hit_forbidden_phrases(self):
        assert run_blacklist_scan("Reproduced with permission from vendor.") != []
        assert run_blacklist_scan("All Rights Reserved") != []
        assert run_blacklist_scan("This section adapted from Pooldial handbook.") != []

    def test_clean_text_returns_empty(self):
        clean = ("Our field techs adjust chlorine to 3 ppm using calcium "
                  "hypochlorite from any reputable supplier.")
        assert run_blacklist_scan(clean) == []

    def test_extra_patterns_are_additive(self):
        text = "This mentions push menu which our module bans."
        extras = [re.compile(r"\bpush menu\b", re.IGNORECASE)]
        assert run_blacklist_scan(text) == []
        assert run_blacklist_scan(text, extra_patterns=extras) != []


class TestChapterMarkdown:
    def test_reads_title_from_first_heading(self, tmp_path):
        p = tmp_path / "ch.md"
        p.write_text("# Chapter Title\n\nBody content here.\n")
        doc = load_chapter_markdown(p, order=1)
        assert doc.title == "Chapter Title"
        assert doc.order == 1
        assert doc.word_count > 0
        assert "Body content" in doc.body


class TestQuizBuilder:
    def test_shapes_questions_correctly(self):
        raw = [
            {"q": "1+1?", "choices": ["1","2","3"], "answer": 1, "explanation": "Basic math."},
            {"q": "Color of sky?", "choices": ["red","blue","green"], "answer": 1},
        ]
        out = build_quiz_questions(raw, module_code="test")
        assert len(out) == 2
        assert out[0]["id"] == "test-q01"
        assert out[0]["correct_choice_ids"] == ["b"]
        assert out[1]["id"] == "test-q02"
        assert out[1]["correct_choice_ids"] == ["b"]
        assert out[1]["explanation"] == ""

    def test_rejects_bad_shape(self):
        with pytest.raises(ValueError):
            build_quiz_questions([{"q": "x", "choices": ["a"], "answer": 0}])
        with pytest.raises(ValueError):
            build_quiz_questions([{"q": "x", "choices": ["a","b"], "answer": 5}])
        with pytest.raises(ValueError):
            build_quiz_questions([{"q": "x"}])  # missing keys


# ─── Upsert idempotency (uses running Mongo) ─────────────────────────
def test_upsert_template_definition_idempotent():
    import asyncio, os
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    from training_seed.seed_common import upsert_template_definition

    async def _run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        code = "unit_test_upsert_smoke"
        doc = {"code": code, "title": "Test", "category": "documents", "is_system": True}
        id1 = await upsert_template_definition(db, doc)
        id2 = await upsert_template_definition(db, doc)
        assert id1 == id2, "second upsert must reuse the same id"
        cnt = await db.template_definitions.count_documents(
            {"code": code, "is_system": True})
        assert cnt == 1, "no duplicates"
        row = await db.template_definitions.find_one(
            {"code": code}, {"_id": 0, "updated_at": 1})
        assert row["updated_at"]
        await db.template_definitions.delete_many({"code": code})
        client.close()

    asyncio.run(_run())
