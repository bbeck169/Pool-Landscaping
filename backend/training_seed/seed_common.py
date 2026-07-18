"""Phase 4 · Batch B / Deliverable 4 — Shared helpers for all seed scripts.

Extracted from `seed_landscape.py`, `seed_pool_supplemental.py`, and
`templates_seed/seed_templates.py`, which previously carried ~90% duplicated
logic. This module is the single source of truth for:

  * IP-safety blacklist scanning (`run_blacklist_scan`, `DEFAULT_BLACKLIST`)
  * Chapter Markdown parsing (`load_chapter_markdown`, `ChapterDoc`)
  * Quiz-question shaping (`build_quiz_questions`)
  * Upsert helpers for training modules + template definitions
    (`upsert_training_module`, `upsert_template_definition`)
  * Shared CLI scaffolding (`cli_main`)

Import path:
    from training_seed.seed_common import (
        run_blacklist_scan, DEFAULT_BLACKLIST,
        load_chapter_markdown, build_quiz_questions,
        upsert_training_module, upsert_template_definition,
        cli_main,
    )
"""
from __future__ import annotations
import argparse, asyncio, json, os, re, sys, uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


# ─── Blacklist scan ─────────────────────────────────────────────────
# All patterns are word-boundary regexes to avoid false hits on legitimate
# prose. Each seed script can extend with domain-specific patterns.
DEFAULT_BLACKLIST: List[re.Pattern] = [re.compile(p, re.IGNORECASE) for p in [
    r"\breproduced with permission\b",
    r"\ball rights reserved\b",
    r"\bexcerpted from\b",
    r"\bcopyright pooldial\b",
    r"\bcopyright cpo\b",
    r"\b\u00a9\s?pooldial\b",
    r"\bcourtesy of pooldial\b",
    r"\badapted from pooldial\b",
    # Vendor copyright markers
    r"\bcopyright hunter\b", r"\bcopyright rain bird\b",
    r"\bcopyright toro\b", r"\bcopyright honda\b",
    r"\bcopyright briggs\b",
    r"\b\u00a9\s?hunter\b", r"\b\u00a9\s?rain bird\b",
    r"\b\u00a9\s?toro\b", r"\b\u00a9\s?honda\b",
    r"\b\u00a9\s?briggs\b",
    r"\bpentair proprietary\b", r"\bhayward proprietary\b",
]]


def run_blacklist_scan(text: str,
                       extra_patterns: Optional[Sequence[re.Pattern]] = None) -> List[str]:
    """Return a list of matched forbidden phrases (empty if clean)."""
    hits: List[str] = []
    patterns = list(DEFAULT_BLACKLIST) + list(extra_patterns or [])
    for pat in patterns:
        if pat.search(text):
            hits.append(pat.pattern)
    return hits


# ─── Chapter markdown ─────────────────────────────────────────────────
@dataclass
class ChapterDoc:
    """Parsed chapter markdown."""
    path: Path
    title: str
    body: str
    word_count: int
    order: int = 0
    frontmatter: Dict[str, Any] = field(default_factory=dict)


def load_chapter_markdown(path: Path, order: int = 0) -> ChapterDoc:
    """Parse a chapter .md file. First `# Heading` becomes `title`.

    Optional YAML-style `--- ... ---` frontmatter is preserved in the
    `frontmatter` field but NOT stripped from the body — downstream
    seeders may keep the raw text for rendering.
    """
    raw = path.read_text(encoding="utf-8")
    frontmatter: Dict[str, Any] = {}
    body = raw
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end > 0:
            for line in raw[4:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    frontmatter[k.strip()] = v.strip()
            body = raw[end + 4:].lstrip("\n")
    first = body.splitlines()[0] if body.splitlines() else ""
    m = re.match(r"^#\s+(.*)$", first)
    title = m.group(1) if m else path.stem
    return ChapterDoc(
        path=path, title=title, body=raw,
        word_count=len(raw.split()), order=order, frontmatter=frontmatter,
    )


# ─── Quiz builder ─────────────────────────────────────────────────
def build_quiz_questions(raw: List[Dict[str, Any]], *,
                          module_code: str = "quiz",
                          letters: Sequence[str] = ("a", "b", "c", "d", "e")) -> List[Dict[str, Any]]:
    """Shape raw quiz entries into the DB schema used by training modules.

    Each raw entry: `{"q": "...", "choices": [...], "answer": 0..n-1, "explanation": "..."}`
    Returns: list of `{id, chapter, prompt, choices[{id,text}], correct_choice_ids, explanation}`.
    """
    out: List[Dict[str, Any]] = []
    for i, q in enumerate(raw, start=1):
        if not isinstance(q, dict) or "q" not in q or "choices" not in q or "answer" not in q:
            raise ValueError(f"quiz question #{i} missing required keys q/choices/answer")
        choices_raw = q["choices"]
        if not isinstance(choices_raw, list) or len(choices_raw) < 2:
            raise ValueError(f"quiz question #{i} needs at least 2 choices")
        if len(choices_raw) > len(letters):
            raise ValueError(f"quiz question #{i} too many choices ({len(choices_raw)})")
        answer_idx = q["answer"]
        if not isinstance(answer_idx, int) or answer_idx < 0 or answer_idx >= len(choices_raw):
            raise ValueError(f"quiz question #{i} answer index out of range")
        choices = [{"id": letters[j], "text": c} for j, c in enumerate(choices_raw)]
        out.append({
            "id": f"{module_code}-q{i:02d}",
            "chapter": q.get("chapter"),
            "prompt": q["q"],
            "choices": choices,
            "correct_choice_ids": [letters[answer_idx]],
            "explanation": q.get("explanation") or "",
        })
    return out


# ─── Upsert helpers ─────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def upsert_training_module(db, module_doc: Dict[str, Any]) -> str:
    """Idempotent upsert by `(code, is_system=True)`. Returns the module id.

    Preserves the existing document id if a system row is already present
    (matches the semantics of the original hand-rolled loops).
    """
    q = {"code": module_doc["code"], "is_system": module_doc.get("is_system", True)}
    existing = await db.training_modules.find_one(q, {"_id": 0, "id": 1})
    doc = dict(module_doc)
    doc["id"] = (existing or {}).get("id") or doc.get("id") or str(uuid.uuid4())
    doc.setdefault("created_at", _now_iso())
    doc["updated_at"] = _now_iso()
    await db.training_modules.update_one(q, {"$set": doc}, upsert=True)
    return doc["id"]


async def upsert_template_definition(db, def_doc: Dict[str, Any]) -> str:
    """Idempotent upsert by `(code, is_system=True)`. Returns the def id."""
    q = {"code": def_doc["code"], "is_system": def_doc.get("is_system", True)}
    existing = await db.template_definitions.find_one(q, {"_id": 0, "id": 1})
    doc = dict(def_doc)
    doc["id"] = (existing or {}).get("id") or doc.get("id") or str(uuid.uuid4())
    doc.setdefault("created_at", _now_iso())
    doc["updated_at"] = _now_iso()
    await db.template_definitions.update_one(q, {"$set": doc}, upsert=True)
    return doc["id"]


# ─── CLI scaffolding ─────────────────────────────────────────────────
def cli_main(seeder_fn: Callable[[argparse.Namespace], None], *, description: str) -> None:
    """Shared argparse for every seed script.

    Adds `--commit`, `--dry-run`, `--verbose`, `--fail-on-blacklist`, and
    dispatches to `seeder_fn(args)`. `--commit` and `--dry-run` are
    mutually exclusive; if neither is given, defaults to dry-run.
    """
    ap = argparse.ArgumentParser(description=description)
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--commit", action="store_true", help="Write to Mongo.")
    grp.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--fail-on-blacklist", action="store_true",
                     help="Exit non-zero on any blacklist hit (default: warn only)")
    args, _extras = ap.parse_known_args()
    if not args.commit and not args.dry_run:
        args.dry_run = True
    seeder_fn(args)
