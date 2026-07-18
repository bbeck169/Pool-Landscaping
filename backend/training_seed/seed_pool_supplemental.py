"""Phase 56.13d1 · Supplemental Pool Training — DRY-RUN seed script.

Modules A/B/C content drafted to `/app/backend/training_seed/
training_pool_supplemental_chapters/`. This script builds an in-memory
representation of the modules + quizzes and, when invoked with
`--commit`, would write them to `db.training_modules` +
`db.training_quiz_questions`. Default mode is **--dry-run** which prints
what it WOULD do without touching the database.

**Blocked by user directive.** Do NOT invoke this script with
`--commit` until the user has spot-checked the .md drafts under
`training_pool_supplemental_chapters/` and given the go-signal to seed.

Author: original in-house content. IP-safety commitments:
  * Zero verbatim OEM manual text.
  * All manufacturer references are name + external URL only.
  * Quiz answers derive from in-house chapter body only.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

CHAPTERS_ROOT = Path(__file__).resolve().parent / "training_pool_supplemental_chapters"

MODULES = [
    {
        "code": "pool-supp-a-filter-cleaning",
        "title": "Filter Cleaning",
        "department": "pool",
        "dir": "module_a_filter_cleaning",
        "summary": "Media types, pressure diagnosis, backwash, cartridge cleaning, DE teardown, O-rings, field triage.",
    },
    {
        "code": "pool-supp-b-shaft-seal",
        "title": "Pump Shaft Seal Replacement",
        "department": "pool",
        "dir": "module_b_shaft_seal",
        "summary": "Seal anatomy, failure signatures, tools, disassembly, install, leak-test, motor-replacement decision.",
    },
    {
        "code": "pool-supp-c-pump-priming",
        "title": "Pump Priming Diagnosis",
        "department": "pool",
        "dir": "module_c_pump_priming",
        "summary": "What prime is, symptoms, water-level basics, suction leaks, check valves, manual prime, escalation.",
    },
]


# IP-safety blacklist — if any chapter body contains one of these phrases,
# the seed refuses. Extended per module in future phases (esp. Module E
# from 56.13d2, which will need Pentair/Hayward keypress-menu phrases).
IP_BLACKLIST = [
    "reproduced with permission",
    "copyright pentair",
    "copyright hayward",
    "copyright jandy",
    "\u00a9 pentair",
    "\u00a9 hayward",
    "\u00a9 jandy",
]

REQUIRED_DISCLAIMER = "Original in-house authorship"


def _read_chapters(module_dir: Path) -> list[dict]:
    out = []
    for md in sorted(module_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        lower = text.lower()
        for phrase in IP_BLACKLIST:
            if phrase.lower() in lower:
                raise SystemExit(f"IP-SAFETY VIOLATION in {md}: contains '{phrase}'")
        if REQUIRED_DISCLAIMER.lower() not in lower:
            print(f"  warn: {md.name} missing disclaimer '{REQUIRED_DISCLAIMER}'", file=sys.stderr)
        title_line = text.splitlines()[0] if text.splitlines() else ""
        m = re.match(r"^#\s+(.*)$", title_line)
        out.append({
            "lesson_id": md.stem,
            "title": m.group(1) if m else md.stem,
            "body_md": text,
            "word_count": len(text.split()),
        })
    return out


def _read_quiz(module_dir: Path) -> dict:
    quiz_path = module_dir / "quiz.json"
    if not quiz_path.exists():
        return {"questions": []}
    return json.loads(quiz_path.read_text(encoding="utf-8"))


def build_seed_payload() -> list[dict]:
    payload = []
    for mod in MODULES:
        module_dir = CHAPTERS_ROOT / mod["dir"]
        if not module_dir.exists():
            raise SystemExit(f"missing module directory: {module_dir}")
        chapters = _read_chapters(module_dir)
        quiz = _read_quiz(module_dir)
        payload.append({
            "code": mod["code"],
            "title": mod["title"],
            "department": mod["department"],
            "summary": mod["summary"],
            "is_system": True,
            "lessons": chapters,
            "quiz": quiz,
        })
    return payload


async def seed_to_db(payload: list[dict]) -> None:
    """Write to Mongo. Called only when --commit is passed."""
    from config import db  # noqa
    for mod in payload:
        await db.training_modules.update_one(
            {"code": mod["code"], "is_system": True},
            {"$set": {
                "code": mod["code"],
                "title": mod["title"],
                "department": mod["department"],
                "summary": mod["summary"],
                "is_system": True,
                "lessons": mod["lessons"],
            }},
            upsert=True,
        )
        # Quiz questions land in a separate collection so a module can be
        # re-seeded without wiping user attempts.
        for i, q in enumerate(mod["quiz"].get("questions", [])):
            await db.training_quiz_questions.update_one(
                {"module_code": mod["code"], "seq": i},
                {"$set": {
                    "module_code": mod["code"],
                    "seq": i,
                    "prompt": q["q"],
                    "choices": q["choices"],
                    "answer_index": q["answer"],
                    "is_system": True,
                }},
                upsert=True,
            )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="Actually write to Mongo (blocked by default).")
    args = ap.parse_args()

    payload = build_seed_payload()

    total_lessons = sum(len(m["lessons"]) for m in payload)
    total_words = sum(l["word_count"] for m in payload for l in m["lessons"])
    total_questions = sum(len(m["quiz"].get("questions", [])) for m in payload)

    print(f"Modules ready: {len(payload)}")
    print(f"Lessons:       {total_lessons}")
    print(f"Words drafted: {total_words}")
    print(f"Quiz Qs:       {total_questions}")
    for m in payload:
        print(f"  - {m['code']} · {len(m['lessons'])} lessons · "
              f"{sum(l['word_count'] for l in m['lessons'])} words · "
              f"{len(m['quiz'].get('questions', []))} quiz Qs")

    if args.commit:
        import asyncio
        print("Committing to Mongo…")
        asyncio.run(seed_to_db(payload))
        print("Done.")
    else:
        print("\nDRY-RUN — no database writes. Pass --commit to seed.")


if __name__ == "__main__":
    main()
