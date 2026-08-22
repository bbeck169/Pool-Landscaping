"""Feb-2026 · P19 — Backfill the empty "Website Visitor" leads.

## What it does
Two prod (``app.plofv.com``) lead rows from 2026-08-20 and 2026-08-21
landed with the P17-fallback name "Website Visitor" and completely
empty contact columns — the tenant's public form used aliased field
names (``full_name`` / ``email_address`` / ``phone_number``) that the
pre-P17 naive extractor silently dropped.  The RAW payload was
persisted on ``form_submissions.values`` though; we re-run those
values through the P17 alias-tolerant extractor
(``routers.marketing._lead_row_from_form_values``) and patch the
matching leads in-place.

## How to invoke

```
# Dry-run FIRST — logs every candidate + planned diff, writes NOTHING.
python -m migrations.task_p19_backfill_empty_website_visitor_leads

# When output looks right, run with --commit to actually write.
python -m migrations.task_p19_backfill_empty_website_visitor_leads --commit
```

Runs against whichever ``MONGO_URL`` the process sees.  Safe to run
on preview and prod independently — the candidate filter is
tenant-agnostic and idempotent (re-runs skip already-populated rows).

## Expected output shape

```python
{
  "total_candidates": 2,
  "backfilled": 2,
  "skipped_no_submission": 0,
  "skipped_no_new_data": 0,
  "skipped_already_populated": 0,
  "dry_run": False,
}
```

## Link resolution
The pre-P17 ``_lead_row_from_form_values`` did NOT stamp a
submission reference on the lead doc — so we can't join by id.
Instead, for each candidate we search ``form_submissions`` for a
row with the same ``tenant_id`` whose ``created_at`` falls within a
±5-minute window of the lead's ``created_at``.  Every lead we've
observed was created within milliseconds of its submission, so the
window is generous by design.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db, logger

# Feb-2026 · P17 extractor — the canonical alias-tolerant mapper.
from routers.marketing import _lead_row_from_form_values


_MATCH_WINDOW = timedelta(minutes=5)


def _parse_iso(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:                                       # noqa: BLE001
            return None
    return None


async def _find_matching_submission(lead: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the closest-in-time form_submissions row on the same
    tenant, within ±5 minutes of the lead's ``created_at``."""
    lead_ts = _parse_iso(lead.get("created_at"))
    if not lead_ts:
        return None
    lo = (lead_ts - _MATCH_WINDOW).isoformat()
    hi = (lead_ts + _MATCH_WINDOW).isoformat()
    cursor = db.form_submissions.find(
        {"tenant_id": lead["tenant_id"],
          "created_at": {"$gte": lo, "$lte": hi}},
        {"_id": 0, "id": 1, "values": 1, "created_at": 1, "form_id": 1},
    )
    best: Optional[Dict[str, Any]] = None
    best_delta = _MATCH_WINDOW.total_seconds() + 1
    async for sub in cursor:
        sub_ts = _parse_iso(sub.get("created_at"))
        if not sub_ts:
            continue
        delta = abs((sub_ts - lead_ts).total_seconds())
        if delta < best_delta:
            best = sub
            best_delta = delta
    return best


def _diff_updates(lead: Dict[str, Any], rebuilt: Dict[str, Any]) -> Dict[str, Any]:
    """Return a $set payload that ONLY overwrites empty lead fields
    where the rebuilt extractor produced a non-empty value.  Never
    clobbers non-empty data — protects human-edited leads."""
    upd: Dict[str, Any] = {}
    for k in ("name", "phone", "email", "address", "service_address",
                "service_interest", "message", "notes"):
        old = lead.get(k)
        new = rebuilt.get(k)
        # Treat None / "" / "Website Visitor" (the P17 fallback name)
        # as "empty" for the ``name`` slot.
        is_empty = (
            old in (None, "") or
            (k == "name" and old == "Website Visitor" and new
              and new != "Website Visitor")
        )
        if is_empty and new not in (None, ""):
            upd[k] = new
    return upd


async def backfill(*, commit: bool = False) -> Dict[str, Any]:
    """Main entrypoint.  ``commit=False`` (default) is dry-run."""
    stats = {
        "total_candidates": 0, "backfilled": 0,
        "skipped_no_submission": 0, "skipped_no_new_data": 0,
        "skipped_already_populated": 0, "dry_run": not commit,
    }
    # Candidate filter: fallback name + BOTH contact channels empty.
    q = {
        "name": "Website Visitor",
        "$and": [
            {"$or": [{"phone": ""}, {"phone": None},
                       {"phone": {"$exists": False}}]},
            {"$or": [{"email": ""}, {"email": None},
                       {"email": {"$exists": False}}]},
        ],
    }
    async for lead in db.leads.find(q, {"_id": 0}):
        stats["total_candidates"] += 1
        lid = lead.get("id")
        tid = lead.get("tenant_id")
        sub = await _find_matching_submission(lead)
        if not sub:
            stats["skipped_no_submission"] += 1
            logger.info(f"[p19] skip_no_submission lead={lid} tenant={tid}")
            continue
        vals = sub.get("values") or {}
        rebuilt = _lead_row_from_form_values(
            tid=tid, vals=vals, source_label=lead.get("source") or "Web Form",
        )
        updates = _diff_updates(lead, rebuilt)
        if not updates:
            stats["skipped_no_new_data"] += 1
            logger.info(
                f"[p19] skip_no_new_data lead={lid} tenant={tid} "
                f"submission={sub.get('id')} (widget genuinely captured nothing)"
            )
            continue
        logger.info(
            f"[p19] {'WOULD backfill' if not commit else 'BACKFILL'} "
            f"lead={lid} tenant={tid} submission={sub.get('id')} "
            f"before={{k: lead.get(k) for k in updates}} "
            f"after={updates}"
        )
        if commit:
            await db.leads.update_one({"id": lid}, {"$set": updates})
        stats["backfilled"] += 1
    logger.info(f"[p19] summary → {stats}")
    return stats


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="P19 · Backfill empty Website Visitor leads",
    )
    parser.add_argument("--commit", action="store_true",
                          help="Write updates (default is dry-run).")
    args = parser.parse_args()
    result = asyncio.run(backfill(commit=args.commit))
    print(result)


if __name__ == "__main__":
    _main()
