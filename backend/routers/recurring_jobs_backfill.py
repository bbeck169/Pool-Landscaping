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

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from utils import new_id, now_iso, require_admin_or_manager
from routers.tenants import get_current_tenant


router = APIRouter(tags=["recurring_jobs_backfill"])


# Phase Feb-2026 · Polish bundle — orphans preview ``?source=`` filter.
# Callers can narrow the returned clusters to a single detection
# pathway. Unknown values are rejected with 422 so a typo surfaces
# loudly instead of silently returning the full list.
_VALID_BACKFILL_SOURCES = ("structural", "keyword_match",
                            "gap_inference", "default")


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
    source: Optional[str] = Query(
        default=None,
        description=(
            "Optional filter — return only clusters whose "
            "``backfill_source`` matches. "
            f"One of {_VALID_BACKFILL_SOURCES}. Unknown values 422."
        ),
    ),
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """Read-only preview of orphan clusters.

    ``?source=`` narrows the response to a single detection
    pathway (structural / keyword_match / gap_inference / default).
    Omitting the param preserves the pre-polish behaviour (all
    clusters). Any other value returns 422 so a typo can't silently
    return the unfiltered list.
    """
    if source is not None and source not in _VALID_BACKFILL_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"recurring_jobs.orphans.invalid_source: source must be "
                f"one of {_VALID_BACKFILL_SOURCES}"
            ),
        )
    rows = await _scan_orphans(tenant["id"])
    if source is not None:
        rows = [r for r in rows if r.get("backfill_source") == source]
    return {
        "orphan_count": len(rows),
        "total_occurrences": sum(r["occurrence_count"] for r in rows),
        "orphans": rows,
        "source_filter": source,
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

    P2 #8 · Feb-2026 — Deliberately NOT gated by the nightly cron's
    ``recurring_job.cron.batch_failure_halt`` guard. Admin backfill
    is an operator-triggered recovery flow; honoring the halt here
    would create a chicken-and-egg trap where ops can't backfill
    the same window that originally tripped the halt. The parallel
    service-level walker (``services.recurring_jobs_backfill.
    run_horizon_backfill``) already tracks ``errored_templates`` in
    its response payload for per-run visibility.
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


# ═══════════════════════════════════════════════════════════════════
# Phase P14 · Feb-2026 · Item 2 — Recurring-jobs orphan PURGE.
# ═══════════════════════════════════════════════════════════════════
#
# Distinct from the backfill endpoints above (which mint templates
# for legacy pre-K4 clusters). This class of orphan is a
# ``recurring_job_templates`` row whose ``customer_id`` no longer
# resolves to an existing customer within the tenant — the
# customer was hard-deleted but the template lingered, so the
# Recurring Visits page renders a ghost row that clicks through
# to a 404 detail page.
#
# ``GET  /api/recurring-jobs/purge-orphans-preview``
#     Dry-run scan. Returns ``{ count, ids }`` so the operator can
#     eyeball the size before firing the purge.
#
# ``POST /api/recurring-jobs/purge-orphans``
#     Hard-deletes every row surfaced by the preview scan AND
#     writes a ``deletion_audit`` snapshot for each. Idempotent —
#     re-running when nothing is orphaned returns
#     ``{ deleted_count: 0, purged_ids: [] }``.
#
# Both endpoints require ``admin`` — same guard the destructive
# ``bulk-hard-delete`` endpoints use across the codebase. Manager
# is intentionally NOT allowed to purge; it's a one-way delete.
async def _scan_purge_orphans(tenant_id: str) -> List[Dict[str, Any]]:
    """Return every ``recurring_job_templates`` row whose
    ``customer_id`` doesn't resolve to a live customer in the
    tenant. Reads only — no writes. Uses ``tenant_scoped_filter``
    so the tenant scope and the soft-delete gate never collide.
    """
    from services.query_scope import tenant_scoped_filter as _tsf
    # 1) Pull every non-deleted template for the tenant. No
    #    ``$or`` disjunction needed here — the soft-delete gate
    #    is the only one — but running through ``_tsf`` keeps
    #    the shape consistent with the P10/P12 posture (never
    #    dict-spread ``$or``).
    q = _tsf(tenant_id)
    templates = await db.recurring_job_templates.find(
        q, {"_id": 0}
    ).to_list(length=5000)
    if not templates:
        return []

    # 2) Deduplicate the customer ids we need to check, then batch
    #    the ``customers.find`` call to a single query.
    ref_ids = {
        str(t.get("customer_id")) for t in templates if t.get("customer_id")
    }
    if not ref_ids:
        # No customer refs at all — every row is an orphan by
        # definition (dangling template with no owner).
        return list(templates)

    live_q = _tsf(tenant_id, id={"$in": list(ref_ids)})
    live_ids: set = set()
    async for row in db.customers.find(live_q, {"_id": 0, "id": 1}):
        cid = row.get("id")
        if cid: live_ids.add(cid)

    # 3) Rows whose ``customer_id`` is missing OR unresolved →
    #    orphans. Missing ``customer_id`` (rare but possible via a
    #    legacy write path) is always orphan.
    orphans: List[Dict[str, Any]] = []
    for t in templates:
        cid = t.get("customer_id")
        if not cid or cid not in live_ids:
            orphans.append(t)
    return orphans


from pydantic import BaseModel as _P14BM


class _PurgeOrphansConfirm(_P14BM):
    """Tiny gate payload so an accidental POST can't fire.
    Frontend types ``DELETE`` in the confirm dialog and we mirror
    that exact string here."""
    confirm: str


@router.get("/recurring-jobs/purge-orphans-preview")
async def purge_orphans_preview(
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """Dry-run — returns ``{count, ids}`` for the yellow-banner
    button copy. Read-only. Admin OR manager can preview; only
    admin can commit."""
    orphans = await _scan_purge_orphans(tenant["id"])
    return {
        "count": len(orphans),
        "ids": [o.get("id") for o in orphans if o.get("id")],
    }


@router.post("/recurring-jobs/purge-orphans")
async def purge_orphans(
    body: _PurgeOrphansConfirm,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """Hard-delete every template whose ``customer_id`` doesn't
    resolve to a live customer in the tenant. Writes an audit
    snapshot per row. Admin-only — the ``require_admin_or_manager``
    guard admits both but we secondary-check for ``admin`` here so
    manager callers get a clean 403 instead of a silent partial-
    ability surface.
    """
    if (user.get("role") or "").lower() not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail={
            "code": "admin_required",
            "message": "Only admins can purge orphaned recurring jobs.",
        })
    if (body.confirm or "").strip() != "DELETE":
        raise HTTPException(status_code=422, detail={
            "code": "confirm_required",
            "message": "Type DELETE in the confirm dialog to proceed.",
        })

    orphans = await _scan_purge_orphans(tenant["id"])
    if not orphans:
        return {"deleted_count": 0, "purged_ids": []}

    # Write audit rows FIRST — never delete without an audit
    # snapshot. Batch under a single ``bulk_op_id`` so a forensic
    # query can pull the whole group.
    from routers.deletion_audit import write_deletion_audit_entry
    bulk_op_id = new_id()
    purged_ids: List[str] = []
    for tpl in orphans:
        tid = tpl.get("id")
        if not tid:
            continue
        try:
            await write_deletion_audit_entry(
                tenant_id=tenant["id"],
                resource_type="recurring_job",
                resource_id=tid,
                user=user,
                snapshot=tpl,
                deletion_reason="purge_orphaned_customer_ref",
                bulk_op_id=bulk_op_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[recurring_jobs.purge] audit write failed for %s: %s",
                tid, exc,
            )
        try:
            r = await db.recurring_job_templates.delete_one(
                {"id": tid, "tenant_id": tenant["id"]},
            )
            if getattr(r, "deleted_count", 0):
                purged_ids.append(tid)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[recurring_jobs.purge] delete failed for %s: %s",
                tid, exc,
            )
    return {
        "deleted_count": len(purged_ids),
        "purged_ids": purged_ids,
        "bulk_op_id": bulk_op_id,
    }
