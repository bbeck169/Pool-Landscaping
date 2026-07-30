"""Phase 10 · Feb-2026 — Response Draft Library (sub-item D).

Extends Phase 6 by auto-capturing successful (status="posted") drafts
into a per-tenant template library that can be surfaced back as
few-shot examples to Claude and picked directly by the operator.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_text(text: str, platform: str) -> str:
    return hashlib.sha256(f"{platform}:{text.strip().lower()}".encode()).hexdigest()[:32]


async def capture_template_from_draft(*, tenant_id: str,
                                          draft: Dict[str, Any]
                                          ) -> Optional[Dict[str, Any]]:
    """Called from Phase 6 update_draft() when status transitions → posted.

    Dedup on (tenant_id, platform, template_hash). Returns the inserted or
    duplicate row (never raises)."""
    text = ((draft.get("edited_text") or "")
            or (draft.get("draft_text") or "")).strip()
    if not text or len(text) < 20:
        return None
    platform = (draft.get("platform") or "generic").lower()
    tone = (draft.get("tone") or "empathetic").lower()
    h = _hash_text(text, platform)
    existing = await db.response_draft_templates.find_one(
        {"tenant_id": tenant_id, "template_hash": h,
          "deleted_at": {"$exists": False}}, {"_id": 0})
    if existing:
        return existing
    row = {"tenant_id": tenant_id,
            "template_id": f"tpl_{uuid.uuid4().hex[:16]}",
            "platform": platform, "tone": tone,
            "source_draft_id": draft.get("draft_id"),
            "template_text": text, "template_hash": h,
            "use_count": 0, "times_used_last_30d": 0,
            "created_at": _now()}
    await db.response_draft_templates.insert_one({**row})
    return row


async def list_templates(*, tenant_id: str, platform: Optional[str] = None,
                            limit: int = 50) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tenant_id,
                          "deleted_at": {"$exists": False}}
    if platform:
        q["platform"] = platform.lower()
    out: List[Dict[str, Any]] = []
    async for r in db.response_draft_templates.find(q, {"_id": 0}).sort(
            [("use_count", -1), ("last_used_at", -1)]).limit(int(limit)):
        out.append(r)
    return out


async def top_templates_for(*, tenant_id: str, platform: str,
                                tone: Optional[str] = None,
                                limit: int = 3) -> List[Dict[str, Any]]:
    """Few-shot look-up before hitting Claude in the draft generator."""
    q: Dict[str, Any] = {"tenant_id": tenant_id,
                          "platform": (platform or "generic").lower(),
                          "deleted_at": {"$exists": False}}
    if tone:
        q["tone"] = tone.lower()
    out: List[Dict[str, Any]] = []
    async for r in db.response_draft_templates.find(q, {"_id": 0}).sort(
            [("use_count", -1), ("last_used_at", -1)]).limit(int(limit)):
        out.append(r)
    return out


async def use_template(*, tenant_id: str,
                          template_id: str) -> Optional[Dict[str, Any]]:
    tpl = await db.response_draft_templates.find_one(
        {"tenant_id": tenant_id, "template_id": template_id,
          "deleted_at": {"$exists": False}}, {"_id": 0})
    if not tpl:
        return None
    now = _now()
    # Recount rolling 30 days: last_used_at + this new use, then increment.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    lua = tpl.get("last_used_at") or ""
    # times_used_last_30d becomes prior_within_30d + 1.
    prior = int(tpl.get("times_used_last_30d") or 0)
    if not lua or lua < cutoff:
        prior = 0  # window rolled over
    new_30d = prior + 1
    r = await db.response_draft_templates.find_one_and_update(
        {"tenant_id": tenant_id, "template_id": template_id,
          "deleted_at": {"$exists": False}},
        {"$inc": {"use_count": 1},
          "$set": {"last_used_at": now,
                    "times_used_last_30d": new_30d}},
        return_document=True, projection={"_id": 0})
    return r


async def soft_delete_template(*, tenant_id: str,
                                   template_id: str) -> Dict[str, Any]:
    r = await db.response_draft_templates.update_one(
        {"tenant_id": tenant_id, "template_id": template_id,
          "deleted_at": {"$exists": False}},
        {"$set": {"deleted_at": _now()}})
    return {"deleted": bool(r.modified_count)}


def render_examples_for_prompt(examples: List[Dict[str, Any]]) -> str:
    """Return a system-suffix block for Claude. Empty string if no examples."""
    if not examples:
        return ""
    lines: List[str] = [
        "\n\nExamples of prior public replies from this business that the "
        "owner has POSTED (use their voice, cadence, and level of formality "
        "— do not copy verbatim):"]
    for i, e in enumerate(examples[:3], 1):
        lines.append(f"\nExample {i} · platform={e.get('platform')} · tone={e.get('tone')}:")
        lines.append(f"\"\"\"\n{(e.get('template_text') or '')[:800]}\n\"\"\"")
    return "".join(lines)
