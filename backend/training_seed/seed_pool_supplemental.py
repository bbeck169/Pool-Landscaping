"""Phase 56.13d1 · Supplemental Pool Training seed script.

Reads .md chapter drafts + quiz.json under
`training_pool_supplemental_chapters/` and either dry-runs
(default) or commits to `db.training_modules` when invoked with
`--commit`.

The DB schema matches the existing `cpo-prep` module:
  * top-level: {id, code, title, department, description, badge_label,
                disclaimer, is_system, tenant_id (null), lessons[], quiz{},
                created_at, updated_at}
  * lessons[]: {id, title, body_md, order, word_count}
  * quiz: {passing_score, questions[]}
  * questions[]: {id, chapter, prompt,
                   choices[{id, text}], correct_choice_ids[str], explanation}

IP-safety:
  * Every .md must carry the "Original in-house authorship" disclaimer.
  * Body blacklist scan for verbatim OEM manual phrases (any hit aborts).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

CHAPTERS_ROOT = Path(__file__).resolve().parent / "training_pool_supplemental_chapters"

MODULES = [
    {
        "code": "pool-filter-cleaning",
        "title": "Filter Cleaning",
        "department": "pool",
        "dir": "module_a_filter_cleaning",
        "description": "Media types, pressure diagnosis, backwash, cartridge cleaning, DE teardown, O-rings, field triage.",
        "badge_label": "Filter Cleaning — Certified",
        "disclaimer": "Original in-house material. External standards (APSP, NSF) cited by name/link only.",
    },
    {
        "code": "pool-shaft-seal",
        "title": "Pump Shaft Seal Replacement",
        "department": "pool",
        "dir": "module_b_shaft_seal",
        "description": "Seal anatomy, failure signatures, tools, disassembly, install, leak-test, motor-replacement decision.",
        "badge_label": "Shaft Seal — Certified",
        "disclaimer": "Original in-house material. OEMs (Pentair, Hayward, Jandy) cited by name/link only.",
    },
    {
        "code": "pool-pump-priming",
        "title": "Pump Priming Diagnosis",
        "department": "pool",
        "dir": "module_c_pump_priming",
        "description": "What prime is, symptom triage, water-level basics, suction leaks, check valves, manual prime, escalation.",
        "badge_label": "Pump Priming — Certified",
        "disclaimer": "Original in-house material. OEMs referenced by name/link only.",
    },
    {
        "code": "pool-jandy-orings",
        "title": "Jandy O-ring Rebuild",
        "department": "pool",
        "dir": "module_d_jandy_orings",
        "description": "Valve families, failure signatures, teardown, reassembly + torque, check valves + JVA, prevention schedule.",
        "badge_label": "Jandy Valves — Certified",
        "disclaimer": "Original in-house material. Jandy referenced by name/link only. Consult the OEM manual for specific model diagrams.",
    },
    {
        "code": "pool-vsp-programming",
        "title": "Variable-Speed Pump Programming",
        "department": "pool",
        "dir": "module_e_vsp_programming",
        "description": "Affinity laws, target-flow philosophy, flow measurement, daily schedule design, controller integration, brand-agnostic troubleshooting.",
        "badge_label": "VSP Programming — Certified",
        "disclaimer": "Original in-house material. Teaches concepts only. All keystrokes and menu paths must be sourced from the OEM manual for the specific model — Pentair (pentair.com) or Hayward (hayward-pool.com).",
    },
]


# IP-safety blacklist. Word-boundary matched so "full-speed 24/7" isn't a
# false-positive against the "speed 2" OEM menu-label fingerprint.
# Each entry is either a plain substring (compiled with word boundaries)
# or a raw regex flagged with `re:` prefix.
IP_BLACKLIST = [
    # Universal (Modules A-E): copyright + republish markers.
    "reproduced with permission",
    "copyright pentair",
    "copyright hayward",
    "copyright jandy",
    "\u00a9 pentair",
    "\u00a9 hayward",
    "\u00a9 jandy",
    # Module E · verbatim OEM menu + keypress fingerprints (word-boundary
    # protected to avoid catching accidental substrings like "full-speed 24/7").
    "intellicenter",
    r"re:\bpush menu\b",
    r"re:\bpress menu\b",
    r"re:\bmenu then edit\b",
    r"re:\bmenu > edit\b",
    r"re:\bpress select\b",
    r"re:\bpress set\b",
    r"re:\bspeed [1-9]\b",       # "Speed 1", "Speed 2", …
    r"re:\baux[1-9]\b",           # AUX1, AUX2, …
    r"re:\barrow to schedule\b",
    r"re:\bpress start\b",
]

# Module-level extra assertions. Every chapter in Module E MUST carry the
# "consult the OEM manual" language so techs are always redirected to the
# authoritative source for exact keystrokes.
E_REQUIRED_PHRASES = [
    "oem manual",
]


def _blacklist_hit(text_lower: str) -> str | None:
    """Return the offending phrase (or None) if any blacklist entry
    matches. Handles both plain-substring and word-boundary regex forms."""
    for pat in IP_BLACKLIST:
        if pat.startswith("re:"):
            if re.search(pat[3:], text_lower):
                return pat[3:]
        else:
            if pat in text_lower:
                return pat
    return None

REQUIRED_DISCLAIMER = "Original in-house authorship"


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
        lesson_id = f"lesson_{i:02d}"
        lessons.append({
            "id": lesson_id,
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
    questions = []
    for i, q in enumerate(raw.get("questions", []), start=1):
        choice_letters = ["a", "b", "c", "d", "e"]
        choices = [{"id": choice_letters[j], "text": c}
                    for j, c in enumerate(q["choices"])]
        answer_id = choice_letters[q["answer"]]
        questions.append({
            "id": f"{module_code}-q{i:02d}",
            "chapter": None,        # not chapter-scoped in this ship
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
    """Direct motor connection using MONGO_URL/DB_NAME (matches config.py
    convention). Kept isolated so a dry-run has no motor/config coupling."""
    import os
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    for mod in payload:
        existing = await db.training_modules.find_one(
            {"code": mod["code"], "is_system": True}, {"_id": 0, "id": 1})
        doc = {**mod}
        if existing and existing.get("id"):
            doc["id"] = existing["id"]
            doc["created_at"] = mod["created_at"]  # keep the write timestamp for re-seed
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
    total_questions = sum(len(m["quiz"]["questions"]) for m in payload)

    print(f"Modules ready: {len(payload)}")
    print(f"Lessons:       {total_lessons}")
    print(f"Words drafted: {total_words}")
    print(f"Quiz Qs:       {total_questions}")
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
