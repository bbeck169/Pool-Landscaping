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
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from .seed_common import (
        run_blacklist_scan, load_chapter_markdown,
        build_quiz_questions, upsert_training_module,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from training_seed.seed_common import (  # type: ignore
        run_blacklist_scan, load_chapter_markdown,
        build_quiz_questions, upsert_training_module,
    )

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


# Module-E extra OEM-menu regex guards (word-boundary).
_MODULE_E_EXTRA = [re.compile(p, re.IGNORECASE) for p in [
    r"\bintellicenter\b",
    r"\bpush menu\b", r"\bpress menu\b",
    r"\bmenu then edit\b", r"\bmenu > edit\b",
    r"\bpress select\b", r"\bpress set\b",
    r"\bspeed [1-9]\b", r"\baux[1-9]\b",
    r"\barrow to schedule\b", r"\bpress start\b",
]]

REQUIRED_DISCLAIMER = "Original in-house authorship"


def _read_chapters(module_dir: Path) -> list[dict]:
    lessons = []
    is_module_e = module_dir.name == "module_e_vsp_programming"
    extra = _MODULE_E_EXTRA if is_module_e else None
    for i, md in enumerate(sorted(module_dir.glob("*.md")), start=1):
        text = md.read_text(encoding="utf-8")
        hits = run_blacklist_scan(text, extra_patterns=extra)
        if hits:
            raise SystemExit(f"IP-SAFETY VIOLATION in {md}: matches '{hits[0]}'")
        if REQUIRED_DISCLAIMER.lower() not in text.lower():
            print(f"  warn: {md.name} missing disclaimer '{REQUIRED_DISCLAIMER}'",
                   file=sys.stderr)
        doc = load_chapter_markdown(md, order=i)
        lessons.append({
            "id": f"lesson_{i:02d}",
            "title": doc.title,
            "body_md": doc.body,
            "order": i,
            "word_count": doc.word_count,
        })
    return lessons


def _build_quiz(module_dir: Path, module_code: str) -> dict:
    quiz_path = module_dir / "quiz.json"
    if not quiz_path.exists():
        return {"passing_score": 0.7, "questions": []}
    raw = json.loads(quiz_path.read_text(encoding="utf-8"))
    questions = build_quiz_questions(raw.get("questions", []), module_code=module_code)
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
    """Direct motor connection using MONGO_URL/DB_NAME."""
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    for mod in payload:
        await upsert_training_module(db, mod)
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
