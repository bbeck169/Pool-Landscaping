"""Phase 56.13a — CPO Prep Module seed script.

Reads the 9 chapter `.md` files + `quiz.json` under `training_cpo_chapters/`
and assembles a single `training_modules` document. Defaults to a dry-run
that prints the payload summary WITHOUT touching the database.

Invocation:
    # Dry-run (safe, default) — prints the assembled payload only.
    python -m backend.training_seed.training_cpo

    # Commit — writes/upserts the module into MongoDB.
    python -m backend.training_seed.training_cpo --commit

The `.md` chapters are the source of truth. The seed script assigns each
chapter an id (e.g., `chapter_01`), stores its raw markdown as
`body_md`, computes `word_count`, and orders lessons by chapter number.
The quiz is copied verbatim from `quiz.json`.

Content invariants enforced (also verified by `tests/test_training_cpo_seed.py`):
- Every quiz question has exactly ONE `correct_choice_ids` entry.
- Badge label = "CPO Prep — Completed" (never "CPO Certified").
- Disclaimer string is present on the module doc.
- Every chapter body is >= 400 and <= 1200 words.

Content licensing: all chapter and quiz text is 100% original, authored
in-house by the Pool & Landscaping engineering team. External standards
(ANSI/APSP, CDC MAHC, VGB Act, ISPSC, ADA, OSHA, NEC, NFPA, IAPMO,
NSF/ANSI) are cited by name and canonical link only. No text is
reproduced from any commercial CPO course.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


MODULE_CODE = "cpo_prep"
MODULE_TITLE = "Certified Pool Operator (CPO) — Prep Course"
MODULE_DEPARTMENT = "pool"
MODULE_DESCRIPTION = (
    "A 9-chapter self-paced practice course covering water chemistry, "
    "sanitization, filtration, hydraulics, disinfection, chemical feed, "
    "facility safety, regulations, and pool math."
)
MODULE_BADGE_LABEL = "CPO Prep — Completed"
MODULE_DISCLAIMER = (
    "This is prep material only. Official CPO certification requires "
    "enrollment with an authorized provider (PHTA / NSPF)."
)

# Repo layout: /app/backend/seed/training_cpo.py ⇒ chapters folder alongside it.
_CHAPTERS_DIR = Path(__file__).resolve().parent / "training_cpo_chapters"
_CHAPTER_FILE_PATTERN = re.compile(r"^(\d{2})_([a-z0-9_]+)\.md$")
_QUIZ_FILE = "quiz.json"

MIN_CHAPTER_WORDS = 400
MAX_CHAPTER_WORDS = 1200


def _word_count(text: str) -> int:
    """Word count using the same rule as `wc -w`: whitespace-delimited tokens."""
    return len([w for w in text.split() if w.strip()])


def _load_chapters() -> List[Dict[str, Any]]:
    """Return an ordered list of {id, title, body_md, order, word_count, sha256}."""
    files = sorted(p for p in _CHAPTERS_DIR.iterdir()
                   if p.is_file() and _CHAPTER_FILE_PATTERN.match(p.name))
    if not files:
        raise FileNotFoundError(f"No chapter files found under {_CHAPTERS_DIR}")

    lessons: List[Dict[str, Any]] = []
    for p in files:
        m = _CHAPTER_FILE_PATTERN.match(p.name)
        if not m:
            continue
        chapter_num, slug = m.group(1), m.group(2)
        body = p.read_text(encoding="utf-8")
        # Prefer the first markdown H1 as the title; fall back to slug.
        title = slug.replace("_", " ").title()
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                break
        wc = _word_count(body)
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        lessons.append({
            "id": f"chapter_{chapter_num}",
            "title": title,
            "body_md": body,
            "order": int(chapter_num),
            "word_count": wc,
            "sha256": sha,
        })
    return lessons


def _load_quiz() -> Dict[str, Any]:
    """Load quiz.json and return the {passing_score, questions[]} shape used by
    the training router. The on-disk quiz keeps additional fields (chapter,
    explanation) that are safe to pass through."""
    quiz_path = _CHAPTERS_DIR / _QUIZ_FILE
    if not quiz_path.exists():
        raise FileNotFoundError(f"quiz file missing: {quiz_path}")
    raw = json.loads(quiz_path.read_text(encoding="utf-8"))
    passing = float(raw.get("meta", {}).get("passing_score") or 0.75)
    questions = raw.get("questions") or []
    # Enforce the "exactly one correct answer" invariant at load time.
    for q in questions:
        cc = q.get("correct_choice_ids") or []
        if not isinstance(cc, list) or len(cc) != 1:
            raise ValueError(
                f"quiz question {q.get('id')} must have exactly ONE correct_choice_ids entry (got {cc!r})"
            )
    return {"passing_score": passing, "questions": questions}


def build_module_payload() -> Dict[str, Any]:
    """Assemble the training_modules document without touching the DB."""
    lessons = _load_chapters()
    # Enforce chapter word-count invariant.
    bad = [(l["id"], l["word_count"]) for l in lessons
           if l["word_count"] < MIN_CHAPTER_WORDS or l["word_count"] > MAX_CHAPTER_WORDS]
    if bad:
        raise ValueError(
            f"chapter word counts out of {MIN_CHAPTER_WORDS}-{MAX_CHAPTER_WORDS} range: {bad}"
        )

    quiz = _load_quiz()

    return {
        "code": MODULE_CODE,
        "title": MODULE_TITLE,
        "department": MODULE_DEPARTMENT,
        "description": MODULE_DESCRIPTION,
        "badge_label": MODULE_BADGE_LABEL,
        "disclaimer": MODULE_DISCLAIMER,
        "is_system": True,          # system module: no tenant_id
        "tenant_id": None,          # explicit for readability
        # Strip the sha256 out of the lesson payload — it's only for spot-check
        # logging in the integrity test, not for the DB row.
        "lessons": [
            {k: v for k, v in l.items() if k != "sha256"} for l in lessons
        ],
        "quiz": quiz,
    }


async def seed_cpo_module(dry_run: bool = True) -> Dict[str, Any]:
    """Assemble the payload and (only when dry_run=False) upsert the row.

    Returns a summary dict: {payload_summary, sha256_by_chapter, committed}.
    """
    payload = build_module_payload()

    # Sha256 per chapter for the integrity test to spot-check.
    lessons = _load_chapters()
    sha_map = {l["id"]: l["sha256"] for l in lessons}
    summary = {
        "code": payload["code"],
        "title": payload["title"],
        "department": payload["department"],
        "badge_label": payload["badge_label"],
        "disclaimer": payload["disclaimer"],
        "lesson_count": len(payload["lessons"]),
        "question_count": len(payload["quiz"]["questions"]),
        "chapter_word_counts": {l["id"]: l["word_count"] for l in payload["lessons"]},
        "chapter_sha256": sha_map,
        "is_system": True,
        "committed": False,
    }

    if dry_run:
        return summary

    # Import DB lazily so the payload builder + integrity tests do not require
    # a live Mongo connection.
    from config import db  # type: ignore
    from utils import new_id, now_iso  # type: ignore

    existing = await db.training_modules.find_one(
        {"code": MODULE_CODE, "is_system": True}, {"_id": 0}
    )
    doc = {
        **payload,
        "updated_at": now_iso(),
    }
    if existing:
        doc["id"] = existing.get("id") or new_id()
        doc["created_at"] = existing.get("created_at") or now_iso()
        await db.training_modules.update_one(
            {"code": MODULE_CODE, "is_system": True}, {"$set": doc}
        )
    else:
        doc["id"] = new_id()
        doc["created_at"] = now_iso()
        await db.training_modules.insert_one(doc)

    summary["committed"] = True
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the CPO prep training module")
    parser.add_argument(
        "--commit", action="store_true",
        help="Actually write to the DB (default is dry-run).",
    )
    args = parser.parse_args()

    summary = asyncio.run(seed_cpo_module(dry_run=not args.commit))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
