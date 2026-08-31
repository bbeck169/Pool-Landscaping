"""Phase F5 · Feb-2026 — one-shot backfill of empty ``Website
Visitor`` leads from their linked ``form_submissions``.

Companion to ``services/lead_extraction.py``.  Walks every lead
that (a) is named the sentinel string ``"Website Visitor"`` OR
(b) has all of ``name`` / ``phone`` / ``email`` empty, finds the
matching ``form_submissions`` row (same tenant, ±60 s around the
lead's ``created_at``), re-runs the F5 extractor against the
preserved raw values, and PATCHes ONLY the blank fields.  Any
already-populated field is preserved.

Boot-safe:
  * Sentinel-guarded.  Runs at most once per deploy — the sentinel
    doc lives in ``migration_status`` with ``key='f5_leads_backfill_v1'``.
  * Idempotent — re-run does nothing when every candidate is
    already filled OR the sentinel is present.
  * Rate-limited (soft) to ``PATCH`` at most ``10 leads/second`` to
    keep Mongo from queueing.
  * Each backfill logs a row to ``lead_backfill_events`` with
    before/after so an ops runbook can audit.

Both **dry-run** and **apply** paths in
``routers/data_repair.py`` use this module (super-admin gated).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.lead_extraction import (
    extract_contact_fields, WEBSITE_VISITOR_FALLBACK,
)


SENTINEL_KEY = "f5_leads_backfill_v1"
SUBMISSION_WINDOW_SECONDS = 60
DEFAULT_RATE_LIMIT_PER_SEC = 10

# Fields we may safely fill on a stale/empty lead.  Anything not
# on this whitelist is never touched.
_BACKFILLABLE_FIELDS = (
    "name", "phone", "email", "address", "service_address",
    "first_name", "last_name", "city", "state", "zip",
    "company_name", "service_interest", "message", "notes",
)


def _is_blank(v: Any) -> bool:
    """Return True for ``None``, ``""``, or a whitespace-only string.

    The migration must only fill blanks — an admin's manually-typed
    value on a previously-empty lead should never be clobbered.
    """
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def _parse_iso(v: Optional[str]) -> Optional[datetime]:
    """Lenient ISO parser — Mongo rows can carry both ``+00:00`` and
    ``Z`` suffixes and either an ISO or a plain ``datetime`` object."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:      # noqa: BLE001
        return None


async def _find_matching_submission(db, lead: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Look up the ``form_submissions`` row that produced ``lead``.

    Strategy (in order):
      1. If the lead carries ``meta.submission_id`` from the widget-
         path upsert, use that directly.
      2. Otherwise, scan for the ONE submission on the same
         tenant whose ``created_at`` falls within ±60 s of the
         lead's ``created_at``.  Ambiguous matches (>1 hit) are
         skipped — never guess.
    """
    sub_id = (lead.get("meta") or {}).get("submission_id")
    if sub_id:
        row = await db.form_submissions.find_one(
            {"id": sub_id, "tenant_id": lead["tenant_id"]},
            {"_id": 0},
        )
        if row:
            return row

    lead_created = _parse_iso(lead.get("created_at"))
    if not lead_created:
        return None
    lo = (lead_created - timedelta(seconds=SUBMISSION_WINDOW_SECONDS)).isoformat()
    hi = (lead_created + timedelta(seconds=SUBMISSION_WINDOW_SECONDS)).isoformat()
    candidates = await db.form_submissions.find({
        "tenant_id": lead["tenant_id"],
        "created_at": {"$gte": lo, "$lte": hi},
    }, {"_id": 0}).to_list(5)
    if len(candidates) == 1:
        return candidates[0]
    return None       # 0 = unrecoverable; >1 = ambiguous, skip


def _values_from_submission(sub: Dict[str, Any]) -> Dict[str, Any]:
    """Different submission shapes store payload under ``values``
    (public-form) OR ``answers`` (widget) OR ``data`` (legacy)."""
    for k in ("values", "answers", "data"):
        v = sub.get(k)
        if isinstance(v, dict) and v:
            return v
    return {}


def _diff_patch(lead: Dict[str, Any],
                 extracted: Dict[str, Optional[str]]) -> Dict[str, Any]:
    """Return the set-ops that would fill every blank whitelisted
    field on ``lead`` from ``extracted``.  Non-blank fields are
    left alone.  Also fills the sentinel-name lead: if the current
    name is exactly ``"Website Visitor"`` and a real name resolved,
    replace it."""
    patch: Dict[str, Any] = {}
    for k in _BACKFILLABLE_FIELDS:
        # Special-case: ``service_address`` mirrors ``address``.
        if k == "service_address":
            new = extracted.get("address")
        elif k == "notes":
            new = extracted.get("message")
        else:
            new = extracted.get(k)
        if new is None or (isinstance(new, str) and not new.strip()):
            continue
        current = lead.get(k)
        # Sentinel name is treated as blank so we can overwrite it.
        if k == "name" and current == WEBSITE_VISITOR_FALLBACK:
            current = None
        if _is_blank(current):
            patch[k] = new
    return patch


async def find_candidate_leads(db, limit: int = 10_000) -> List[Dict[str, Any]]:
    """Return every lead that MAY be repairable by this migration."""
    cur = db.leads.find({
        "$or": [
            {"name": WEBSITE_VISITOR_FALLBACK},
            {"$and": [
                {"$or": [{"name": None}, {"name": ""}]},
                {"$or": [{"email": None}, {"email": ""}]},
                {"$or": [{"phone": None}, {"phone": ""}]},
            ]},
        ],
    }, {"_id": 0})
    return await cur.to_list(limit)


async def _plan_one(db, lead: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any],
                                                                    Dict[str, Any]]]:
    """Return ``(submission, patch)`` for a lead, or None if not
    repairable (no matching submission, or nothing to fill)."""
    sub = await _find_matching_submission(db, lead)
    if not sub:
        return None
    vals = _values_from_submission(sub)
    if not vals:
        return None
    extracted = extract_contact_fields(vals)
    patch = _diff_patch(lead, extracted)
    if not patch:
        return None
    return sub, patch


async def plan(db, limit: int = 10_000) -> Dict[str, Any]:
    """Dry-run: return the plan without mutating anything.

    Response shape mirrors F2's data-repair pattern:
      * ``candidates_total`` — count of leads matching the search.
      * ``would_change`` — subset that HAS a resolvable submission
        AND at least one blank field to fill.
      * ``samples`` — up to 10 example ``(lead_id, patch)`` tuples.
    """
    candidates = await find_candidate_leads(db, limit=limit)
    would: List[Dict[str, Any]] = []
    for lead in candidates:
        plan_row = await _plan_one(db, lead)
        if plan_row:
            _, patch = plan_row
            would.append({
                "lead_id": lead["id"],
                "tenant_id": lead["tenant_id"],
                "current_name": lead.get("name"),
                "patch_keys": sorted(patch.keys()),
                "patch": patch,
            })
    return {
        "candidates_total": len(candidates),
        "would_change": len(would),
        "samples": would[:10],
        "scan_timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _write_event(db, lead: Dict[str, Any],
                        sub: Dict[str, Any],
                        patch: Dict[str, Any],
                        actor_id: Optional[str]) -> None:
    """Audit row per repair — write to ``lead_backfill_events``."""
    from utils import new_id, now_iso
    await db.lead_backfill_events.insert_one({
        "id": new_id(),
        "tenant_id": lead["tenant_id"],
        "migration": SENTINEL_KEY,
        "lead_id": lead["id"],
        "submission_id": sub.get("id"),
        "before": {k: lead.get(k) for k in patch.keys()},
        "after": patch,
        "actor_id": actor_id,
        "created_at": now_iso(),
    })


async def apply_backfill(db, *,
                            actor_id: Optional[str] = None,
                            rate_limit_per_sec: int = DEFAULT_RATE_LIMIT_PER_SEC,
                            limit: int = 10_000) -> Dict[str, Any]:
    """Run the migration for real — PATCH every eligible lead."""
    candidates = await find_candidate_leads(db, limit=limit)
    changed = 0
    skipped = 0
    for lead in candidates:
        plan_row = await _plan_one(db, lead)
        if not plan_row:
            skipped += 1
            continue
        sub, patch = plan_row
        await db.leads.update_one(
            {"id": lead["id"], "tenant_id": lead["tenant_id"]},
            {"$set": patch},
        )
        await _write_event(db, lead, sub, patch, actor_id)
        changed += 1
        if rate_limit_per_sec and rate_limit_per_sec > 0:
            await asyncio.sleep(1.0 / rate_limit_per_sec)
    return {
        "candidates_total": len(candidates),
        "changed": changed,
        "skipped": skipped,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


async def run_if_needed(db) -> Optional[Dict[str, Any]]:
    """Boot-safe entry.  Runs the migration once per deploy via a
    sentinel row in ``migration_status``.  Returns None on a
    subsequent boot when the sentinel is already present."""
    from utils import now_iso
    sentinel = await db.migration_status.find_one(
        {"key": SENTINEL_KEY}, {"_id": 0, "completed_at": 1},
    )
    if sentinel and sentinel.get("completed_at"):
        return None
    result = await apply_backfill(db, actor_id="system:boot")
    await db.migration_status.update_one(
        {"key": SENTINEL_KEY},
        {"$set": {"key": SENTINEL_KEY,
                    "completed_at": now_iso(),
                    "summary": result}},
        upsert=True,
    )
    return result
