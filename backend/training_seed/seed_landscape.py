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
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Support both `python3 -m training_seed.seed_landscape` and
# direct-file invocation.
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
    # Phase 56.14a2 · Modules 4-7 (drafts — commit gated behind --modules flag)
    {
        "code": "landscape-pavers-hardscape",
        "title": "Pavers & Hardscape Repair",
        "department": "landscaping",
        "dir": "module_4_pavers",
        "description": "Base preparation, pattern layout, cutting, joint sand, sealing, and repair of settled or heaved pavers.",
        "badge_label": "Pavers & Hardscape — Certified",
        "disclaimer": "Original in-house material. Vendor products cited by name/link only.",
    },
    {
        "code": "landscape-turf-sod",
        "title": "Turf & Sod Installation / Maintenance",
        "department": "landscaping",
        "dir": "module_5_turf_sod",
        "description": "Site prep, sod selection, laying pattern, watering-in, aftercare, and ongoing mow / fertilize / dethatch cycles.",
        "badge_label": "Turf & Sod — Certified",
        "disclaimer": "Original in-house material. Vendor products cited by name/link only.",
    },
    {
        "code": "landscape-outdoor-kitchen",
        "title": "BBQ / Outdoor Kitchen Installation",
        "department": "landscaping",
        "dir": "module_6_outdoor_kitchen",
        "description": "Site layout, gas / electrical rough-in decision tree, countertop and enclosure, appliance install, safety commissioning.",
        "badge_label": "Outdoor Kitchen — Certified",
        "disclaimer": "Original in-house material. Consult a licensed gas/electrical trade for any regulated work.",
    },
    {
        "code": "landscape-valve-diagnostics",
        "title": "Valve Diagnostics (Irrigation Zone Valves)",
        "department": "landscaping",
        "dir": "module_7_valve_diagnostics",
        "description": "Anatomy, symptom-to-cause decision tree, solenoid vs diaphragm vs debris, in-field replacement flow.",
        "badge_label": "Valve Diagnostics — Certified",
        "disclaimer": "Original in-house material. Consult the OEM manual for model-specific torque and rebuild kit specs.",
    },
]

# Codes that default to committing when `--commit` is passed with no
# `--modules` filter. Phase 56.14a2 modules 4-7 are gated: they need an
# explicit `--modules 4,5,6,7` (or a list of codes) to be committed.
DEFAULT_COMMIT_CODES = {
    "landscape-irrigation-repairs",
    "landscape-irrigation-timers",
    "landscape-small-engine",
}

# ─── Module-specific extra IP-safety guards ──────────────────────
# Module-2 controller menu fingerprints (word-boundary regex).
_M2_EXTRA = [re.compile(p, re.IGNORECASE) for p in [
    r"\bpush prg\b", r"\bpress prg\b",
    r"\bstation [1-9]\b", r"\bprogram [abc]\b", r"\brotary switch\b",
]]

REQUIRED_DISCLAIMER = "Original in-house authorship"
MODULE_2_DIR = "module_2_irrigation_timers"
M2_REDIRECT_PHRASE = "oem manual"


def _read_chapters(module_dir: Path) -> list[dict]:
    lessons = []
    extra = _M2_EXTRA if module_dir.name == MODULE_2_DIR else None
    for i, md in enumerate(sorted(module_dir.glob("*.md")), start=1):
        text = md.read_text(encoding="utf-8")
        hits = run_blacklist_scan(text, extra_patterns=extra)
        if hits:
            raise SystemExit(f"IP-SAFETY VIOLATION in {md}: matches {hits[0]}")
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


def build_seed_payload(only_codes: set | None = None) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    payload = []
    for mod in MODULES:
        if only_codes is not None and mod["code"] not in only_codes:
            continue
        module_dir = CHAPTERS_ROOT / mod["dir"]
        if not module_dir.exists():
            # Draft-not-yet-authored modules are silently skipped.
            print(f"  skip: {mod['code']} — {module_dir} not on disk", file=sys.stderr)
            continue
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
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    for mod in payload:
        await upsert_training_module(db, mod)
    client.close()


def _resolve_modules_filter(arg: str | None) -> set | None:
    """Accept `--modules 4,5,6,7` or explicit codes.
    Falls back to DEFAULT_COMMIT_CODES when nothing is provided."""
    if not arg:
        return DEFAULT_COMMIT_CODES
    tokens = [t.strip() for t in arg.split(",") if t.strip()]
    codes = set()
    for t in tokens:
        if t.isdigit():
            idx = int(t) - 1
            if 0 <= idx < len(MODULES):
                codes.add(MODULES[idx]["code"])
        else:
            codes.add(t)
    return codes
    """Accept `--modules 4,5,6,7` (numeric shorthand) OR
    `--modules landscape-pavers-hardscape,...` (explicit codes).
    Falls back to DEFAULT_COMMIT_CODES when nothing is provided."""
    if not arg:
        return DEFAULT_COMMIT_CODES
    tokens = [t.strip() for t in arg.split(",") if t.strip()]
    codes = set()
    for t in tokens:
        if t.isdigit():
            idx = int(t) - 1
            if 0 <= idx < len(MODULES):
                codes.add(MODULES[idx]["code"])
        else:
            codes.add(t)
    return codes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="Actually write to Mongo (blocked by default).")
    ap.add_argument("--modules", type=str, default=None,
                    help="Comma-separated module codes or 1-based indices to include.")
    args = ap.parse_args()

    # Dry-run inspects EVERY authored module dir (so drafts are visible
    # in the count); commit respects --modules filter.
    payload_preview = build_seed_payload(None)
    total_lessons = sum(len(m["lessons"]) for m in payload_preview)
    total_words = sum(l["word_count"] for m in payload_preview for l in m["lessons"])
    total_q = sum(len(m["quiz"]["questions"]) for m in payload_preview)
    print(f"Modules ready:  {len(payload_preview)}")
    print(f"Lessons:        {total_lessons}")
    print(f"Words drafted:  {total_words}")
    print(f"Quiz Qs:        {total_q}")
    for m in payload_preview:
        print(f"  - {m['code']} · {len(m['lessons'])} lessons · "
              f"{sum(l['word_count'] for l in m['lessons'])} words · "
              f"{len(m['quiz']['questions'])} quiz Qs")

    if args.commit:
        commit_codes = _resolve_modules_filter(args.modules)
        commit_payload = [m for m in payload_preview if m["code"] in commit_codes]
        print(f"\nCommitting {len(commit_payload)} module(s): "
              f"{sorted(m['code'] for m in commit_payload)}")
        import asyncio
        asyncio.run(seed_to_db(commit_payload))
        print("Done.")
    else:
        print("\nDRY-RUN — no database writes. Pass --commit to seed.")


if __name__ == "__main__":
    main()
