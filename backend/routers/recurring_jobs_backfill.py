"""Feb-2026 P0 · Recurring-jobs orphan backfill.

Bug reported by user:
    "80+ customers set up as recurring jobs from the Schedule page
     don't appear on the Recurring Visits page."

Root cause:
    The Schedule flow (``/jobs/new`` → cadence != one_time) pre-
    materializes 12-24 ``db.jobs`` rows (one per occurrence) BUT
    also — since Phase K4 in Feb-2026 — POSTs a companion template
    row to ``db.recurring_job_templates``. Two ways to end up with
    orphan clusters:
      1. The customer was scheduled BEFORE Phase K4 landed. The
         pre-K4 code path only inserted ``db.jobs`` rows and never
         wrote a template. No retroactive migration was run.
      2. Post-K4, the template POST is best-effort (a 403 / 500
         from ``/recurring-jobs`` is swallowed with a soft toast).
         For an operator running through 80+ setups in a batch,
         some subset silently missed the template mirror.

Recurring Visits admin page reads from
``db.recurring_job_templates`` exclusively, so orphan clusters are
invisible until we mint templates for them.

This module exposes two admin endpoints:

    GET  /api/recurring-jobs/orphans
        Read-only dry-run. Returns the distinct clusters of
        ``db.jobs`` rows tagged ``is_recurring=true`` (or
        ``recurring_type != "none"``) that have no matching
        template. Response is a preview the operator can eyeball
        BEFORE running the mutating backfill.

    POST /api/recurring-jobs/backfill-orphans
        Materializes ``db.recurring_job_templates`` documents for
        every distinct cluster the GET endpoint returned. Idempotent
        — clusters that already have a template are skipped. Returns
        the count created + skipped.

Cluster key
-----------
Two ``db.jobs`` rows belong to the same cluster iff they share
``(tenant_id, customer_id, service_type, frequency_or_cadence)``.
For clusters whose cadence is unknowable (e.g. legacy rows without
a ``recurrence_rule`` / ``cadence`` field), we infer from the
inter-visit gap of the first two occurrences (7 days → weekly,
14 → biweekly, ~30 → monthly). Unclassifiable clusters get
``frequency="weekly"`` as a safe default.

Rate limit
----------
None — admin-only, expected to run a handful of times ever. The
mutating endpoint stamps ``created_by_backfill=True`` on every
template it creates so an audit can query for them later.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from config import db, logger
from utils import new_id, now_iso, require_admin_or_manager
from routers.tenants import get_current_tenant


router = APIRouter(tags=["recurring_jobs_backfill"])


# Phase Feb-2026 · Recurring-jobs backfill · keyword broaden.
# Ordered most-specific-first — biweekly must beat weekly, and
# semi_annual must beat annual/yearly. ``annual`` / ``yearly`` are
# not in the ``VALID_FREQ`` enum (see routers/recurring_jobs.py),
# so they collapse into ``custom`` — same downstream shape.
_KEYWORD_FREQ_PATTERNS: List[tuple] = [
    ("biweekly",    re.compile(r"\bbi[-\s]?weekly\b", re.IGNORECASE)),
    ("weekly",      re.compile(r"\bweekly\b", re.IGNORECASE)),
    ("monthly",     re.compile(r"\bmonthly\b", re.IGNORECASE)),
    ("quarterly",   re.compile(r"\bquarterly\b", re.IGNORECASE)),
    ("semi_annual", re.compile(r"\bsemi[-\s]?annual\b", re.IGNORECASE)),
    ("custom",      re.compile(r"\b(?:annual|yearly)\b", re.IGNORECASE)),
]


def _keyword_frequency(job: dict) -> Optional[str]:
    """Scan title + description + notes for a cadence keyword. Returns
    the canonical ``VALID_FREQ`` value or ``None`` when no match.
    Most-specific pattern wins (biweekly > weekly, etc.)."""
    hay = " ".join([
        str(job.get("title") or ""),
        str(job.get("description") or ""),
        str(job.get("notes") or ""),
    ])
    if not hay.strip():
        return None
    for freq, pat in _KEYWORD_FREQ_PATTERNS:
        if pat.search(hay):
            return freq
    return None


def _is_recurring_row(job: dict) -> bool:
    """Best-effort detection of a recurring row.

    Historical rows carry ANY of these hints. All are checked because
    Schedule setup flows have evolved shape across releases. Feb-2026
    broaden: title / description / notes keyword ("weekly", "monthly",
    "annual", …) also count so pre-K4 rows that only had textual
    hints get pulled in.
    """
    if job.get("is_recurring") is True: return True
    if job.get("recurring") is True: return True
    if job.get("recurring_template_id"): return True
    r = job.get("recurrence") or job.get("cadence") or ""
    if isinstance(r, str) and r and r.lower() not in ("none", "one_time", "one-time"):
        return True
    # Keyword fallback — pulls in title-only recurring rows.
    if _keyword_frequency(job):
        return True
    return False


def _infer_frequency(job: dict) -> Optional[str]:
    """Return the cadence stored on the job row, if any."""
    for k in ("frequency", "cadence", "recurrence", "recurring_type"):
        v = job.get(k)
        if isinstance(v, str) and v.strip().lower() not in ("", "none", "one_time"):
            v = v.strip().lower()
            # Normalise legacy synonyms.
            if v in ("weekly", "biweekly", "monthly", "quarterly", "semi_annual", "custom"):
                return v
            if v in ("bi_weekly", "bi-weekly"):
                return "biweekly"
    return None


def _infer_from_gap_days(days: int) -> str:
    if days <= 8:  return "weekly"
    if days <= 16: return "biweekly"
    if days <= 45: return "monthly"
    if days <= 100: return "quarterly"
    if days <= 200: return "semi_annual"
    return "weekly"


def _parse_iso_date(s: Any) -> Optional[date]:
    if not s: return None
    if isinstance(s, datetime): return s.date()
    if isinstance(s, date): return s
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except Exception:
        return None


async def _scan_orphans(tenant_id: str) -> List[Dict[str, Any]]:
    """Return one row per orphan cluster.

    Row shape::

        {
          "customer_id": str,
          "customer_name": str,
          "service_type": str,
          "frequency": str,
          "occurrence_count": int,
          "first_scheduled_date": "YYYY-MM-DD",
          "last_scheduled_date":  "YYYY-MM-DD",
          "sample_job_id": str,
          "day_of_week": Optional[int],
          "day_of_month": Optional[int],
          "price_cents": int,
          "assigned_tech_id": Optional[str],
          "crew_id": Optional[str],
          "work_class": Optional[str],
        }
    """
    # 1. All active templates in this tenant — cluster key set.
    tpl_cur = db.recurring_job_templates.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "customer_id": 1, "service_type": 1, "frequency": 1,
         "id": 1},
    )
    tpl_keys: set = set()
    tpl_ids: set = set()
    async for tpl in tpl_cur:
        tpl_keys.add((
            tpl.get("customer_id"),
            (tpl.get("service_type") or "").strip().lower(),
            (tpl.get("frequency") or "").strip().lower(),
        ))
        if tpl.get("id"):
            tpl_ids.add(tpl["id"])

    # 2. Walk db.jobs looking for recurring rows.
    cur = db.jobs.find(
        {"tenant_id": tenant_id},
        # Project only the fields we need — keeps memory bounded even
        # on tenants with thousands of jobs.
        {"_id": 0, "id": 1, "customer_id": 1, "customer_name": 1,
         "service_type": 1, "title": 1, "scheduled_date": 1,
         "frequency": 1, "cadence": 1, "recurrence": 1,
         "recurring_type": 1, "recurring": 1, "is_recurring": 1,
         "recurring_template_id": 1, "price": 1, "price_cents": 1,
         "assigned_tech_id": 1, "technician_id": 1, "crew_id": 1,
         "work_class": 1, "day_of_week": 1, "day_of_month": 1},
    )
    clusters: Dict[tuple, List[dict]] = defaultdict(list)
    async for j in cur:
        if not _is_recurring_row(j):
            continue
        # Rows tied to an existing template can never be orphans.
        rtid = j.get("recurring_template_id")
        if rtid and rtid in tpl_ids:
            continue
        cid = j.get("customer_id")
        stype = (j.get("service_type") or j.get("title") or "").strip()
        # Feb-2026 broaden: fall back to keyword-match on the job's
        # title/description so a legacy "Weekly Pool Service" row
        # (no structural cadence field) still clusters under the
        # right frequency instead of falling through to the gap
        # inference default.
        freq_hint = _infer_frequency(j) or _keyword_frequency(j) or ""
        key = (cid, stype.lower(), freq_hint.lower())
        clusters[key].append(j)

    out: List[Dict[str, Any]] = []
    for key, rows in clusters.items():
        cid, stype_lo, freq_lo = key
        # Filter out clusters whose template already exists.
        if key in tpl_keys:
            continue
        # Order by scheduled_date so first/last make sense.
        def _sd(j):
            d = _parse_iso_date(j.get("scheduled_date"))
            return d or date.min
        rows.sort(key=_sd)
        first, last = rows[0], rows[-1]
        # Infer freq if the row hints didn't set it.  Priority:
        # (1) structural cadence field on any row  →  ``structural``
        # (2) keyword match in any row's title/description → ``keyword_match``
        # (3) inter-visit gap of the first two occurrences → ``gap_inference``
        # (4) safe default weekly → ``default``
        freq = freq_lo or None
        source: Optional[str] = None
        if freq:
            # ``freq`` came from the cluster key — determine which
            # pathway supplied it by re-checking whether any row
            # carries a structural cadence field.
            if any(_infer_frequency(r) for r in rows):
                source = "structural"
            else:
                source = "keyword_match"
        else:
            for r in rows:
                kw = _keyword_frequency(r)
                if kw:
                    freq = kw
                    source = "keyword_match"
                    break
        if not freq and len(rows) >= 2:
            d0 = _parse_iso_date(rows[0].get("scheduled_date"))
            d1 = _parse_iso_date(rows[1].get("scheduled_date"))
            if d0 and d1:
                freq = _infer_from_gap_days((d1 - d0).days)
                source = "gap_inference"
        if not freq:
            freq = "weekly"
            source = "default"
        # Money.
        price_cents = int(
            first.get("price_cents") or
            round((float(first.get("price") or 0) * 100))
        )
        entry = {
            "customer_id": cid,
            "customer_name": first.get("customer_name") or "",
            "service_type": first.get("service_type") or first.get("title") or "Pool Cleaning",
            "frequency": freq,
            "occurrence_count": len(rows),
            "first_scheduled_date": (
                _parse_iso_date(first.get("scheduled_date")).isoformat()
                if _parse_iso_date(first.get("scheduled_date")) else None
            ),
            "last_scheduled_date": (
                _parse_iso_date(last.get("scheduled_date")).isoformat()
                if _parse_iso_date(last.get("scheduled_date")) else None
            ),
            "sample_job_id": first.get("id"),
            "day_of_week": first.get("day_of_week"),
            "day_of_month": first.get("day_of_month"),
            "price_cents": price_cents,
            "assigned_tech_id": first.get("assigned_tech_id")
                or first.get("technician_id"),
            "crew_id": first.get("crew_id"),
            "work_class": first.get("work_class") or "service",
            "backfill_source": source,
        }
        # For weekly/biweekly, infer day_of_week from the first
        # occurrence's ISO weekday if the row didn't set one.
        if entry["frequency"] in ("weekly", "biweekly") and entry["day_of_week"] is None:
            d0 = _parse_iso_date(first.get("scheduled_date"))
            if d0:
                # ISO weekday: Mon=0..Sun=6 per RecurringJobIn.
                entry["day_of_week"] = (d0.weekday()) % 7
        if entry["frequency"] == "monthly" and entry["day_of_month"] is None:
            d0 = _parse_iso_date(first.get("scheduled_date"))
            if d0:
                entry["day_of_month"] = d0.day
        out.append(entry)
    return out


@router.get("/recurring-jobs/orphans")
async def list_orphans(
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """Read-only preview of orphan clusters."""
    rows = await _scan_orphans(tenant["id"])
    return {
        "orphan_count": len(rows),
        "total_occurrences": sum(r["occurrence_count"] for r in rows),
        "orphans": rows,
    }


@router.post("/recurring-jobs/backfill-orphans")
async def backfill_orphans(
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """Materialize a template row for every orphan cluster.

    Idempotent — running twice with no new orphans is a no-op. Each
    generated template is stamped ``created_by_backfill=True`` so a
    tenant admin can audit which rows came from the migration and
    which from the standard create flow.

    ``last_generated_through`` is set to the cluster's last
    pre-materialized occurrence so the nightly generator won't
    double-book any occurrence already in ``db.jobs``.
    """
    tenant_id = tenant["id"]
    orphans = await _scan_orphans(tenant_id)
    created = 0
    skipped_existing = 0
    for o in orphans:
        # Guard: template may have been created between GET and POST
        # in a concurrent tenant session.
        exists = await db.recurring_job_templates.find_one(
            {
                "tenant_id": tenant_id,
                "customer_id": o["customer_id"],
                "service_type": {"$regex": f"^{o['service_type']}$",
                                      "$options": "i"},
                "frequency": o["frequency"],
            },
            {"_id": 0, "id": 1},
        )
        if exists:
            skipped_existing += 1
            continue
        doc = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "customer_id": o["customer_id"],
            "customer_name": o["customer_name"],
            "service_type": o["service_type"],
            "frequency": o["frequency"],
            "day_of_week": o.get("day_of_week"),
            "day_of_month": o.get("day_of_month"),
            "start_date": o["first_scheduled_date"]
                or date.today().isoformat(),
            "end_date": None,
            "assigned_tech_id": o.get("assigned_tech_id"),
            "crew_id": o.get("crew_id"),
            "price_cents": o["price_cents"],
            "notes": "",
            "active": True,
            "work_class": o.get("work_class") or "service",
            "recurrence_never_ends": True,
            "last_generated_through": o.get("last_scheduled_date"),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "created_by": user.get("id"),
            "created_by_backfill": True,
            # Feb-2026 broaden: preserve which detection path minted
            # the row so an admin audit can filter keyword-match
            # rows separately from structural / gap / default.
            "backfill_source": o.get("backfill_source") or "structural",
        }
        try:
            await db.recurring_job_templates.insert_one(doc)
            created += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[recurring_jobs.backfill] insert failed for "
                f"{o.get('customer_name')!r}: {exc}"
            )
    return {
        "ok": True,
        "created": created,
        "skipped_existing": skipped_existing,
        "orphan_count_scanned": len(orphans),
    }
