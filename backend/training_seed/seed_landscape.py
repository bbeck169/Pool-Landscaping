"""Phase 56.14a1 · Landscape Training seed script (DRY-RUN by default).

Reads .md chapter drafts + quiz.json under
`training_landscape_chapters/` and either dry-runs (default) or commits
to `db.training_modules` when invoked with `--commit`.

Same schema as `seed_pool_supplemental.py`: matches the existing
`cpo-prep` module.

IP-safety:
  * Every .md must carry the "Original in-house authorship" disclaimer.
  * Universal blacklist: verbatim OEM manual copyright / republish markers.
  * Module-2 blacklist: OEM controller-menu keypress fingerprints (word-boundary
    regex — no false positives on prose like "smart start times").
  * Every Module-2 chapter must contain "OEM manual" as a positive redirect.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

CHAPTERS_ROOT = Path(__file__).resolve().parent / "training_landscape_chapters"

MODULES = [
    {
        "code": "landscape-irrigation-repairs",
        "title": "Irrigation Repairs",
        "department": "landscaping",
        "dir": "module_1_irrigation_repairs",
        "description": "System anatomy, diagnostic sequence, head/lateral/valve/wire repair, backflow compliance.",
        "badge_label": "Irrigation Repairs — Certified",
        "disclaimer": "Original in-house material. Hunter, Rain Bird, Toro cited by name/link only. Consult OEM manual for model-specific specs.",
    },
    {
        "code": "landscape-irrigation-timers",
        "title": "Irrigation Timers / Controllers",
        "department": "landscaping",
        "dir": "module_2_irrigation_timers",
        "description": "Controller anatomy, programs/start times, ETo + smart controllers, sensors, flow monitoring, Wi-Fi gotchas, diagnostics.",
        "badge_label": "Irrigation Controllers — Certified",
        "disclaimer": "Original in-house material. Concepts only — consult the OEM manual for exact keypad/app steps.",
    },
    {
        "code": "landscape-small-engine",
        "title": "Small Engine Repair & Maintenance",
        "department": "landscaping",
        "dir": "module_3_small_engine",
        "description": "Engine landscape, three-condition rule, carburetor, ignition, oil/air/fuel, 2-stroke, field diagnostics.",
        "badge_label": "Small Engine — Certified",
        "disclaimer": "Original in-house material. Honda, Briggs & Stratton, Kohler, Kawasaki, Echo, Stihl cited by name/link only.",
    },
]


# IP-safety blacklist. Same word-boundary regex philosophy as the pool
# supplemental script. Module-2 has extra scrutiny (controller menus).
IP_BLACKLIST = [
    "reproduced with permission",
    "copyright hunter",
    "copyright rain bird",
    "copyright toro",
    "copyright honda",
    "copyright briggs",
    "\u00a9 hunter",
    "\u00a9 rain bird",
    "\u00a9 toro",
    "\u00a9 honda",
    "\u00a9 briggs",
    # Module 2 controller menu fingerprints (word-boundary regex).
    r"re:\bpush prg\b",
    r"re:\bpress prg\b",
    r"re:\bstation [1-9]\b",
    r"re:\bprogram [abc]\b",
    r"re:\brotary switch\b",
]

REQUIRED_DISCLAIMER = "Original in-house authorship"
MODULE_2_DIR = "module_2_irrigation_timers"
M2_REDIRECT_PHRASE = "oem manual"


def _blacklist_hit(text_lower: str) -> str | None:
    for pat in IP_BLACKLIST:
        if pat.startswith("re:"):
            if re.search(pat[3:], text_lower):
                return pat[3:]
        else:
            if pat in text_lower:
                return pat
    return None


def _read_chapters(module_dir: Path) -> list[dict]:
    lessons = []
    for i, md in enumerate(sorted(module_dir.glob("*.md")), start=1):
        text = md.read_text(encoding="utf-8")
        hit = _blacklist_hit(text.lower())
        if hit:
            raise SystemExit(f"IP-SAFETY VIOLATION in {md}: matches '{hit}'")
        if REQUIRED_DISCLAIMER.lower() not in text.lower():
            print(f"  warn: {md.name} missing disclaimer '{REQUIRED_DISCLAIMER}'",
                   file=sys.stderr)
        title_line = text.splitlines()[0] if text.splitlines() else ""
        m = re.match(r"^#\s+(.*)$", title_line)
        title = m.group(1) if m else md.stem
        lessons.append({
            "id": f"lesson_{i:02d}",
            "title": title,
            "body_md": text,
            "order": i,
            "word_count": len(text.split()),
        })
    return lessons


def _build_quiz(module_dir: Path, module_code: str) -> dict:
    quiz_path = module_dir / "quiz.json"
    if not quiz_path.exists():
        return {"passing_score": 0.7, "questions": []}
    raw = json.loads(quiz_path.read_text(encoding="utf-8"))
    letters = ["a", "b", "c", "d", "e"]
    questions = []
    for i, q in enumerate(raw.get("questions", []), start=1):
        choices = [{"id": letters[j], "text": c} for j, c in enumerate(q["choices"])]
        answer_id = letters[q["answer"]]
        questions.append({
            "id": f"{module_code}-q{i:02d}",
            "chapter": None,
            "prompt": q["q"],
            "choices": choices,
            "correct_choice_ids": [answer_id],
            "explanation": q.get("explanation") or "",
        })
    return {"passing_score": 0.7, "questions": questions}


def build_seed_payload() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    payload = []
    for mod in MODULES:
        module_dir = CHAPTERS_ROOT / mod["dir"]
        if not module_dir.exists():
            raise SystemExit(f"missing module directory: {module_dir}")
        lessons = _read_chapters(module_dir)
        quiz = _build_quiz(module_dir, mod["code"])
        payload.append({
            "code": mod["code"],
            "title": mod["title"],
            "department": mod["department"],
            "description": mod["description"],
            "badge_label": mod["badge_label"],
            "disclaimer": mod["disclaimer"],
            "is_system": True,
            "tenant_id": None,
            "lessons": lessons,
            "quiz": quiz,
            "created_at": now,
            "updated_at": now,
        })
    return payload


async def seed_to_db(payload: list[dict]) -> None:
    import os
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    for mod in payload:
        existing = await db.training_modules.find_one(
            {"code": mod["code"], "is_system": True}, {"_id": 0, "id": 1})
        doc = {**mod}
        if existing and existing.get("id"):
            doc["id"] = existing["id"]
        else:
            doc["id"] = str(uuid.uuid4())
        await db.training_modules.update_one(
            {"code": mod["code"], "is_system": True},
            {"$set": doc},
            upsert=True,
        )
    client.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="Actually write to Mongo (blocked by default).")
    args = ap.parse_args()

    payload = build_seed_payload()
    total_lessons = sum(len(m["lessons"]) for m in payload)
    total_words = sum(l["word_count"] for m in payload for l in m["lessons"])
    total_q = sum(len(m["quiz"]["questions"]) for m in payload)
    print(f"Modules ready: {len(payload)}")
    print(f"Lessons:       {total_lessons}")
    print(f"Words drafted: {total_words}")
    print(f"Quiz Qs:       {total_q}")
    for m in payload:
        print(f"  - {m['code']} · {len(m['lessons'])} lessons · "
              f"{sum(l['word_count'] for l in m['lessons'])} words · "
              f"{len(m['quiz']['questions'])} quiz Qs")

    if args.commit:
        import asyncio
        print("Committing to Mongo…")
        asyncio.run(seed_to_db(payload))
        print("Done.")
    else:
        print("\nDRY-RUN — no database writes. Pass --commit to seed.")


if __name__ == "__main__":
    main()
