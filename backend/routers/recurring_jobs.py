"""Phase 51.I · Recurring-Job Scheduling Engine.

Collection `recurring_job_templates` — schema in the router docstring.
Every generated job carries `recurring_template_id`. A unique index on
`(recurring_template_id, scheduled_date)` guarantees idempotent
regeneration.

Endpoints (all admin/super_admin unless noted):
    POST   /api/recurring-jobs
    GET    /api/recurring-jobs?active=true
    GET    /api/recurring-jobs/{id}
    PATCH  /api/recurring-jobs/{id}
    DELETE /api/recurring-jobs/{id}                        (soft-delete)
    POST   /api/recurring-jobs/{id}/generate?through=YYYY-MM-DD

The nightly cron `run_recurring_job_generator()` walks every active
template across every tenant and generates jobs from
`last_generated_through + 1` through `today + 14 days`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import new_id, now_iso, require_admin, require_admin_or_manager
from routers.tenants import get_current_tenant

router = APIRouter(tags=["recurring_jobs"])

VALID_FREQ = {"weekly", "biweekly", "monthly", "quarterly", "semi_annual", "custom"}

# Feb-2026 · Monthly nth-weekday recurrence (RFC 5545 BYDAY + BYSETPOS).
VALID_MONTHLY_PATTERN = {"day_of_month", "nth_weekday"}
VALID_NTH_WEEK = {"first": 1, "second": 2, "third": 3, "fourth": 4, "last": -1}


class RecurringJobIn(BaseModel):
    customer_id: str
    service_type: str
    frequency: str
    interval_days: Optional[int] = Field(None, ge=1, le=365)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    day_of_month: Optional[int] = Field(None, ge=1, le=31)
    start_date: str
    end_date: Optional[str] = None
    assigned_tech_id: Optional[str] = None
    # Phase H9 · Feb-2026 — assignment can now target a crew
    # instead of an individual tech. Only one of the two may be
    # set on any given template; the endpoint rejects the
    # both-set case with HTTP 400. When ``crew_id`` is set, the
    # generator preserves it on materialized job instances so
    # the F6a scheduling semantic (crew → any tech in
    # ``crew.tech_ids``) resolves at schedule time.
    crew_id: Optional[str] = None
    price_cents: int = 0
    notes: str = ""
    allow_sunday: bool = False
    active: bool = True
    # Feb-2026 · Recurring Jobs — is_active + generator gate.
    # Distinct from the legacy ``active`` flag (which stays True
    # by default for backwards compat with existing callers). The
    # nightly generator now gates on ``is_active`` AND
    # ``start_date <= today`` so a template can be created in a
    # draft state without immediately materializing jobs. New API
    # records default to ``False`` — legacy DB rows are backfilled
    # to ``True`` by ``services/migrations/recurring_templates_
    # is_active_backfill.py``.
    is_active: bool = False
    # Feb-2026 · Never-end recurrence. When True, `end_date` is forced
    # to None on save so `_next_occurrences` walks unbounded (capped
    # only by the nightly 14-day generator horizon → rolling forever).
    # Explicit intent flag so the UI can render a distinct "runs until
    # manually stopped" state instead of a silently-blank End date.
    recurrence_never_ends: bool = False
    # Feb-2026 · Monthly nth-weekday pattern (e.g. "3rd Friday",
    # "Last Wednesday"). Only meaningful when frequency=="monthly".
    # ``day_of_month`` (default) preserves the legacy always-on-the-Nth
    # behavior. ``nth_weekday`` requires both companion fields below.
    monthly_pattern: Optional[str] = "day_of_month"
    monthly_nth_week: Optional[str] = None  # first|second|third|fourth|last
    monthly_weekday: Optional[int] = Field(None, ge=0, le=6)  # 0=Mon…6=Sun
    # Feb 2026 · Work-class dimension carried through the recurring
    # template so materialized occurrences inherit the service/repair
    # tag. Optional at the schema level; validation in the create/
    # update handlers via ``services.work_class.normalize_work_class``.
    work_class: Optional[str] = "service"
    # Phase K4 · Feb-2026 — optional generator cursor at create time.
    # The Schedule flow uses this to seed the template with a cursor
    # equal to the last date it pre-materialized so the H10 daily
    # generator won't double-book any of those occurrences. Callers
    # that omit it default to None (generator starts from
    # ``start_date``).
    last_generated_through: Optional[str] = None
    # Phase K4 · Feb-2026 — property_id passthrough so Schedule-side
    # multi-property customers keep their pick when the template is
    # created alongside the pre-materialized jobs.
    property_id: Optional[str] = None


class RecurringJobPatch(BaseModel):
    service_type: Optional[str] = None
    frequency: Optional[str] = None
    interval_days: Optional[int] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    assigned_tech_id: Optional[str] = None
    # Phase H9 · Feb-2026 — see create-body doc. On PATCH we
    # allow explicit ``None`` to clear the assignment; the
    # combined-picker UI sends the opposite key as ``None`` when
    # a user flips between tech and crew, so the ``$set`` needs
    # to actually stamp the field (not just omit it).
    crew_id: Optional[str] = None
    price_cents: Optional[int] = None
    notes: Optional[str] = None
    allow_sunday: Optional[bool] = None
    active: Optional[bool] = None
    # Feb-2026 · Recurring Jobs — is_active on patch.
    is_active: Optional[bool] = None
    recurrence_never_ends: Optional[bool] = None
    monthly_pattern: Optional[str] = None
    monthly_nth_week: Optional[str] = None
    monthly_weekday: Optional[int] = None
    # Feb 2026 · Retag pass-through for recurring templates.
    work_class: Optional[str] = None


async def _resolve_crew_ref(tenant_id: str, crew_id: Optional[str]
                                ) -> Optional[Dict[str, Any]]:
    """Phase H9 · Feb-2026 — Load a crew by id, tenant-scoped.
    Returns ``{id, name}`` on success, ``None`` when the caller
    passed no crew_id. Raises HTTP 404 when a non-empty crew_id
    doesn't resolve — cross-tenant refs and typos both land here.
    """
    if not crew_id:
        return None
    row = await db.crews.find_one(
        {"id": crew_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1},
    )
    if not row:
        raise HTTPException(404, "crew not found")
    return row


def _reject_double_assignment(*, assigned_tech_id: Optional[str],
                                    crew_id: Optional[str]) -> None:
    """Phase H9 · Feb-2026 — assign to tech OR crew, never both."""
    if assigned_tech_id and crew_id:
        raise HTTPException(
            400,
            {"detail": "assignment_conflict",
             "hint": ("A recurring template can be assigned to a "
                      "tech OR a crew, not both. Clear one and "
                      "try again.")},
        )


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _validate(body: RecurringJobIn | RecurringJobPatch,
               skip_dow_gate: bool = False) -> None:
    freq = body.frequency
    if freq is not None and freq not in VALID_FREQ:
        raise HTTPException(422, f"frequency must be one of {sorted(VALID_FREQ)}")
    if freq == "custom" and not body.interval_days:
        raise HTTPException(422, "interval_days is required for custom frequency")
    if freq in ("weekly", "biweekly") and body.day_of_week is None \
            and not skip_dow_gate:
        raise HTTPException(422, "day_of_week (0=Mon…6=Sun) is required for weekly/biweekly")
    if freq == "monthly":
        # Feb-2026 · monthly can be classic day-of-month or nth-weekday.
        pattern = getattr(body, "monthly_pattern", None) or "day_of_month"
        if pattern not in VALID_MONTHLY_PATTERN:
            raise HTTPException(422,
                f"monthly_pattern must be one of {sorted(VALID_MONTHLY_PATTERN)}")
        if pattern == "day_of_month" and body.day_of_month is None:
            raise HTTPException(422, "day_of_month is required for monthly (day_of_month pattern)")
        if pattern == "nth_weekday":
            nth = getattr(body, "monthly_nth_week", None)
            wd = getattr(body, "monthly_weekday", None)
            if nth not in VALID_NTH_WEEK:
                raise HTTPException(422,
                    f"monthly_nth_week must be one of {sorted(VALID_NTH_WEEK.keys())}")
            if wd is None:
                raise HTTPException(422,
                    "monthly_weekday (0=Mon…6=Sun) is required for nth_weekday pattern")
    # Feb-2026 · P47 — quarterly / semi_annual reuse the classic
    # day_of_month sub-mode. ``nth_weekday`` is intentionally NOT
    # supported for the new cadences — quarterly-3rd-Friday is out
    # of scope per spec.
    if freq in ("quarterly", "semi_annual"):
        if body.day_of_month is None:
            raise HTTPException(422,
                f"day_of_month is required for {freq}")
        if (getattr(body, "monthly_pattern", None)
                and body.monthly_pattern == "nth_weekday"):
            raise HTTPException(422,
                f"monthly_pattern=nth_weekday is not supported for {freq}")


def _nth_weekday_of_month(year: int, month: int, nth: str, weekday: int) -> Optional[date]:
    """Return the date of the ``nth`` occurrence of ``weekday`` in the
    given month, or None if it doesn't exist (e.g. "5th Friday" in a
    month with only 4 Fridays — caller should treat as skip). ``nth``
    is a key of ``VALID_NTH_WEEK``; ``weekday`` uses Python's
    ``date.weekday()`` convention (Mon=0…Sun=6).
    """
    import calendar as _cal
    n = VALID_NTH_WEEK.get(nth)
    if n is None:
        return None
    _, last_day = _cal.monthrange(year, month)
    if n == -1:
        # Walk backwards from the last day to find the target weekday.
        d = date(year, month, last_day)
        while d.weekday() != weekday:
            d -= timedelta(days=1)
        return d
    # Find the first matching weekday, then step forward (n-1) weeks.
    first = date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    candidate = first + timedelta(days=delta + (n - 1) * 7)
    if candidate.month != month:
        return None  # e.g. 5th Friday when only 4 exist
    return candidate


def _next_occurrences(tpl: Dict[str, Any], anchor: date,
                        horizon_end: date, max_count: int = 60) -> List[date]:
    """Return every occurrence date strictly ≥ anchor and ≤ horizon_end
    that satisfies the template's frequency rules. Sunday is skipped by
    default unless `allow_sunday` is True. Respects `end_date`."""
    start = _parse_date(tpl.get("start_date")) or anchor
    end_date = _parse_date(tpl.get("end_date"))
    allow_sunday = bool(tpl.get("allow_sunday"))
    freq = tpl.get("frequency")
    dow = tpl.get("day_of_week")
    dom = tpl.get("day_of_month")
    interval = int(tpl.get("interval_days") or 7)

    # Anchor the walk: never before `start_date`.
    walker = max(start, anchor)
    if end_date and walker > end_date:
        return []
    hard_stop = min(horizon_end, end_date) if end_date else horizon_end

    out: List[date] = []
    if freq == "weekly":
        # Snap forward to next matching weekday.
        while walker.weekday() != dow:
            walker += timedelta(days=1)
        step = timedelta(days=7)
        while walker <= hard_stop and len(out) < max_count:
            if allow_sunday or walker.weekday() != 6:
                out.append(walker)
            walker += step
    elif freq == "biweekly":
        while walker.weekday() != dow:
            walker += timedelta(days=1)
        # Anchor cadence to start_date so biweekly stays aligned across regenerations.
        base = start
        while base.weekday() != dow:
            base += timedelta(days=1)
        diff = (walker - base).days
        offset = diff % 14
        if offset:
            walker += timedelta(days=(14 - offset))
        step = timedelta(days=14)
        while walker <= hard_stop and len(out) < max_count:
            if allow_sunday or walker.weekday() != 6:
                out.append(walker)
            walker += step
    elif freq == "monthly":
        # Feb-2026 · monthly branches on ``monthly_pattern``. Default
        # (day_of_month) preserves the legacy always-on-the-Nth
        # behavior; ``nth_weekday`` walks the calendar picking e.g.
        # the 3rd Friday of each month (skipping months without a
        # matching Nth-week when nth != "last").
        import calendar as _cal
        pattern = tpl.get("monthly_pattern") or "day_of_month"
        y, m = walker.year, walker.month
        if pattern == "nth_weekday":
            nth = tpl.get("monthly_nth_week")
            wd = tpl.get("monthly_weekday")
            if nth in VALID_NTH_WEEK and wd is not None:
                while len(out) < max_count:
                    candidate = _nth_weekday_of_month(y, m, nth, int(wd))
                    if candidate is not None and candidate >= walker:
                        if candidate > hard_stop:
                            break
                        if allow_sunday or candidate.weekday() != 6:
                            out.append(candidate)
                    m += 1
                    if m > 12:
                        m = 1; y += 1
        else:
            # Classic day-of-month.
            while len(out) < max_count:
                last_day = _cal.monthrange(y, m)[1]
                picked_day = min(dom or 1, last_day)
                candidate = date(y, m, picked_day)
                if candidate < walker:
                    # push to next month
                    m += 1
                    if m > 12:
                        m = 1; y += 1
                    continue
                if candidate > hard_stop:
                    break
                if allow_sunday or candidate.weekday() != 6:
                    out.append(candidate)
                m += 1
                if m > 12:
                    m = 1; y += 1
    elif freq in ("quarterly", "semi_annual"):
        # Feb-2026 · P47 — step by 3 (quarterly) or 6 (semi_annual)
        # months, reusing the same day-of-month clamp as monthly's
        # classic mode. ``nth_weekday`` is not supported for these
        # cadences (validated on create). Sunday-skip semantics
        # match the monthly branch: Sundays are included regardless
        # of ``allow_sunday``.
        from services.recurrence_math import advance_months, MONTH_STEP
        step_months = MONTH_STEP[freq]
        candidate_dom = dom or 1
        # Anchor to start_date so the "Nth of the month" survives
        # month-length clamping — we always compute from ``start``
        # + N*step_months rather than compounding the previous
        # (possibly clamped) date.
        n = 0
        # Fast-forward past ``walker`` so the first emitted date is
        # ≥ walker.
        while True:
            candidate = advance_months(start, step_months * n,
                                              candidate_dom)
            if candidate >= walker:
                break
            n += 1
        while len(out) < max_count:
            candidate = advance_months(start, step_months * n,
                                              candidate_dom)
            if candidate > hard_stop:
                break
            out.append(candidate)
            n += 1
    elif freq == "custom":
        step = timedelta(days=interval)
        # Anchor cadence to start_date so custom stays aligned.
        base = start
        diff = (walker - base).days
        offset = diff % interval
        if offset:
            walker += timedelta(days=(interval - offset))
        while walker <= hard_stop and len(out) < max_count:
            if allow_sunday or walker.weekday() != 6:
                out.append(walker)
            walker += step
    return out


async def _ensure_indexes():
    try:
        await db.recurring_job_templates.create_index(
            [("tenant_id", 1), ("active", 1)]
        )
        # Feb-2026 · P0 index remediation.
        #
        # The prior index was ``unique=True, sparse=True`` on
        # ``(recurring_template_id, scheduled_date)`` — intended to
        # dedup regenerated recurring occurrences. Sparse on a
        # *compound* index still indexes every document that has at
        # least one of the keys, and ``scheduled_date`` is present on
        # every job. That meant every non-recurring job (where
        # ``recurring_template_id`` was ``null`` or missing) was
        # indexed under the same synthetic ``null`` bucket keyed by
        # date → the SECOND non-recurring job for any customer on
        # any given date collided with the unique constraint and the
        # request 500'd with ``E11000 duplicate key``. Root cause
        # for the Terry-Hernandez ``POST /api/jobs`` 500 reported on
        # production (repro-clean in preview because this index was
        # never lazily created here).
        #
        # Fix: replace with a *partial* unique index whose filter
        # excludes docs that lack ``recurring_template_id``. Now the
        # dedup guarantee is preserved for actual recurring
        # occurrences, and non-recurring jobs are free to duplicate
        # per date.
        target_name = "recurring_template_id_1_scheduled_date_1"
        info = await db.jobs.index_information()
        existing = info.get(target_name)
        needs_recreate = False
        if existing is not None:
            # Motor returns the raw index spec. ``partialFilterExpression``
            # signals the new shape; ``sparse`` signals the legacy one.
            if not existing.get("partialFilterExpression"):
                needs_recreate = True
        if needs_recreate:
            try:
                await db.jobs.drop_index(target_name)
                logger.info(
                    "[recurring_jobs.indexes] dropped legacy sparse-unique "
                    "index — replacing with partial-unique variant"
                )
            except Exception as drop_err:
                logger.warning(
                    f"[recurring_jobs.indexes] drop legacy index failed: "
                    f"{drop_err}"
                )
        if needs_recreate or existing is None:
            await db.jobs.create_index(
                [("recurring_template_id", 1), ("scheduled_date", 1)],
                unique=True,
                # MongoDB partialFilterExpression only supports equality,
                # $exists:true, $gt/$gte/$lt/$lte, $type, $and, $or.
                # $ne / $not are rejected. Since ``recurring_template_id``
                # is a string uuid when set, ``$type: "string"`` cleanly
                # excludes both null and missing values.
                partialFilterExpression={
                    "recurring_template_id": {"$type": "string"},
                },
                name=target_name,
            )
    except Exception as e:
        logger.warning(f"recurring_jobs index: {e}")


@router.post("/recurring-jobs")
async def create_recurring(body: RecurringJobIn,
                             user: dict = Depends(require_admin_or_manager),
                             tenant: dict = Depends(get_current_tenant)):
    # Feb-2026 · Phase — Recommended Schedule auto-assign v1.
    # Detect the trigger BEFORE ``_validate`` runs so the weekly/
    # biweekly day-of-week gate doesn't reject a payload we're
    # about to auto-fill. When the caller left BOTH the tech and
    # the day unset, we try to hug an existing route slot; a
    # successful pick mutates the body so downstream code sees a
    # fully-populated shape.
    def _empty(v):
        return v is None or (isinstance(v, str) and not v.strip())
    _wants_auto_assign = (_empty(body.assigned_tech_id)
                             and _empty(body.crew_id)
                             and body.day_of_week is None)
    auto: Dict[str, Any] = {"auto_assigned": False,
                              "reason": "manual_override",
                              "assigned_tech_id": None,
                              "day_of_week": None,
                              "technician_name": None,
                              "extra_minutes": 0,
                              "source_meters": 0}
    if _wants_auto_assign:
        try:
            from services.recurring_jobs.route_proximity import (
                compute_route_proximity_assignment,
            )
            auto = await compute_route_proximity_assignment(
                tenant_id=tenant["id"], body=body.dict(),
            )
        except Exception as _aa_exc:                            # noqa: BLE001
            logger.warning("[auto-assign] compute failed: %s", _aa_exc)
            auto = {"auto_assigned": False,
                     "reason": "internal_error",
                     "assigned_tech_id": None,
                     "day_of_week": None,
                     "technician_name": None,
                     "extra_minutes": 0,
                     "source_meters": 0}
        if auto.get("auto_assigned"):
            # Mutate the incoming body so ``_validate`` sees the
            # freshly-filled tech + day and the doc composition
            # below persists them.
            body.assigned_tech_id = auto["assigned_tech_id"]
            body.day_of_week = auto["day_of_week"]

    # ── Validation ─────────────────────────────────────────────────
    # Skip only the weekly/biweekly day-of-week gate when auto-
    # assign was attempted (even if it fell through — spec §2 says
    # the record persists without a tech/day in that case). All
    # other validation still runs.
    if _wants_auto_assign and not auto.get("auto_assigned") \
            and body.frequency in ("weekly", "biweekly") \
            and body.day_of_week is None:
        # Auto-assign wanted to fill in the day + tech but the
        # window was empty (no peer routes / no geocode). Persist
        # the record anyway per spec §2 — skip only the DOW gate.
        _validate(body, skip_dow_gate=True)
    else:
        _validate(body)
    # Feb-2026 · Recurring Jobs · is_active gate. On create,
    # ``start_date`` is already required by ``RecurringJobIn`` so
    # this is only a defense-in-depth pair-check for callers that
    # somehow smuggle an empty ``start_date`` past Pydantic.
    if body.is_active and not (body.start_date or "").strip():
        raise HTTPException(422, {"detail": "start_date_required_for_active"})
    _reject_double_assignment(
        assigned_tech_id=body.assigned_tech_id, crew_id=body.crew_id,
    )
    await _ensure_indexes()
    cust = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0, "name": 1}
    )
    if not cust:
        raise HTTPException(404, "customer not found")
    # Phase H9 · Resolve crew name for the denorm (UI reads it
    # to avoid a follow-up crew lookup).
    crew = await _resolve_crew_ref(tenant["id"], body.crew_id)
    doc = body.dict()

    # Feb-2026 · Never-end intent overrides end_date. If the caller
    # said "runs until manually stopped", clear the end date so the
    # generator walks forever.
    if doc.get("recurrence_never_ends"):
        doc["end_date"] = None
    doc.update({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_name": cust.get("name"),
        # Phase H9 · denorm crew name at write-time so the UI
        # can render assignment without a separate crew fetch.
        "crew_name": (crew or {}).get("name"),
        # Phase K4 · Feb-2026 — respect a caller-supplied cursor.
        # Callers that omit ``last_generated_through`` keep the
        # historical None so the generator starts at ``start_date``.
        "last_generated_through": doc.get("last_generated_through"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user["id"],
        # Feb-2026 · Recommended Schedule auto-assign v1 —
        # persistent breadcrumbs so the list + detail views can
        # render the "Auto-assigned via route proximity" badge
        # without a follow-up call. See
        # ``memory/FEATURE_RECOMMEND_SCHEDULE_AUTO_ASSIGN.md``.
        "auto_assigned": bool(auto.get("auto_assigned")),
        "auto_assign_reason": auto.get("reason"),
        "auto_assign_extra_minutes": int(auto.get("extra_minutes") or 0),
        "auto_assign_source_meters": int(auto.get("source_meters") or 0),
    })
    await db.recurring_job_templates.insert_one(doc)
    doc.pop("_id", None)
    # Attach the client-only ``auto_assign_info`` bundle so the
    # frontend can pick the toast variant + render the badge in one
    # round-trip. Kept out of the persisted doc so the DB shape
    # stays flat.
    doc["auto_assign_info"] = {
        "auto_assigned": bool(auto.get("auto_assigned")),
        "reason": auto.get("reason"),
        "technician_id": auto.get("assigned_tech_id"),
        "technician_name": auto.get("technician_name"),
        "day_of_week": auto.get("day_of_week"),
        "extra_minutes": int(auto.get("extra_minutes") or 0),
    }
    return doc


@router.get("/recurring-jobs")
async def list_recurring(active: Optional[bool] = Query(None),
                          user: dict = Depends(require_admin_or_manager),
                          tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if active is not None:
        q["active"] = bool(active)
    rows = await db.recurring_job_templates.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    # Attach the next 3 upcoming occurrences so the UI table can render a preview.
    today = date.today()
    horizon = today + timedelta(days=90)
    for r in rows:
        try:
            occ = _next_occurrences(r, today, horizon, max_count=3)
            r["upcoming"] = [d.isoformat() for d in occ]
        except Exception:
            r["upcoming"] = []
    return {"items": rows, "count": len(rows)}


@router.get("/recurring-jobs/{tpl_id}")
async def get_recurring(tpl_id: str,
                          user: dict = Depends(require_admin_or_manager),
                          tenant: dict = Depends(get_current_tenant)):
    doc = await db.recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "template not found")
    today = date.today()
    horizon = today + timedelta(days=90)
    doc["upcoming"] = [d.isoformat() for d in _next_occurrences(doc, today, horizon, max_count=6)]
    return doc


@router.patch("/recurring-jobs/{tpl_id}")
async def patch_recurring(tpl_id: str, body: RecurringJobPatch,
                            user: dict = Depends(require_admin_or_manager),
                            tenant: dict = Depends(get_current_tenant)):
    _validate(body)
    raw = body.dict(exclude_unset=True)
    # Feb-2026 · Recurring Jobs · is_active gate. Rejects
    # ``is_active=true`` when neither the incoming patch nor the
    # existing doc carries a ``start_date``. Look up the current
    # doc lazily so the ok-path stays a single write.
    if raw.get("is_active") is True:
        _incoming_start = (raw.get("start_date") or "").strip()
        if not _incoming_start:
            _existing = await db.recurring_job_templates.find_one(
                {"id": tpl_id, "tenant_id": tenant["id"]},
                {"_id": 0, "start_date": 1},
            )
            if not (_existing or {}).get("start_date"):
                raise HTTPException(
                    422, {"detail": "start_date_required_for_active"},
                )
    # Phase H9 · Feb-2026 — assignment fields (``assigned_tech_id``,
    # ``crew_id``) must survive as explicit ``None`` in the ``$set``
    # so a "flip from crew to tech" wipes the opposite side. The
    # legacy filter dropped None to preserve nullable-optional
    # semantics; carve those fields out.
    _ASSIGN_KEYS = {"assigned_tech_id", "crew_id"}
    updates: Dict[str, Any] = {
        k: v for k, v in raw.items()
        if v is not None or k == "active" or k == "is_active" or k in _ASSIGN_KEYS
    }
    # If the caller supplied both assignment fields with non-None
    # values, reject before writing.
    _reject_double_assignment(
        assigned_tech_id=updates.get("assigned_tech_id"),
        crew_id=updates.get("crew_id"),
    )
    # If ``crew_id`` is being SET (non-None), resolve it and stamp
    # the denorm name. If cleared to None, drop the denorm too.
    if "crew_id" in updates:
        if updates["crew_id"]:
            crew = await _resolve_crew_ref(tenant["id"], updates["crew_id"])
            updates["crew_name"] = (crew or {}).get("name")
        else:
            updates["crew_name"] = None
    # Feb-2026 · Never-end intent overrides end_date on patch too.
    if updates.get("recurrence_never_ends") is True:
        updates["end_date"] = None
    updates["updated_at"] = now_iso()
    res = await db.recurring_job_templates.update_one(
        {"id": tpl_id, "tenant_id": tenant["id"]},
        {"$set": updates},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "template not found")
    return await db.recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.delete("/recurring-jobs/{tpl_id}")
async def delete_recurring(tpl_id: str,
                             hard: bool = Query(False),
                             user: dict = Depends(require_admin_or_manager),
                             tenant: dict = Depends(get_current_tenant)):
    """Delete a recurring-job template.

    * ``hard=false`` (default) — SOFT delete: flip ``active`` (and
      the new ``is_active`` gate) to False. Existing behavior; the
      template stays in the collection so historical children keep
      resolving via ``recurring_template_id`` denorm.
    * ``hard=true`` — HARD delete:
        - Physically remove the template row from
          ``db.recurring_job_templates``.
        - Cancel every future-scheduled child job derived from it
          (``status == 'scheduled'`` AND ``scheduled_date > today``)
          — completed / in-progress children are preserved.
        - Emit an ``audit_logs`` entry so the delete is traceable.
    Both branches are admin-only (same auth as create/patch).
    """
    if hard:
        # Fetch the doc first so the audit entry carries a snapshot
        # + we can 404 cleanly when the id is unknown.
        tpl = await db.recurring_job_templates.find_one(
            {"id": tpl_id, "tenant_id": tenant["id"]}, {"_id": 0},
        )
        if not tpl:
            raise HTTPException(404, "template not found")
        # Cancel future-scheduled children (leave completed/in-
        # progress rows alone).
        today_iso = date.today().isoformat()
        cancel_res = await db.jobs.update_many(
            {
                "tenant_id": tenant["id"],
                "recurring_template_id": tpl_id,
                "status": "scheduled",
                "scheduled_date": {"$gt": today_iso},
            },
            {"$set": {"status": "cancelled",
                       "cancelled_at": now_iso(),
                       "cancelled_reason": "recurring_template_hard_deleted",
                       "updated_at": now_iso()}},
        )
        # Remove the template row.
        await db.recurring_job_templates.delete_one(
            {"id": tpl_id, "tenant_id": tenant["id"]},
        )
        # Audit trail — same collection every other admin action
        # writes to (best-effort, never blocks the delete).
        try:
            await db.audit_logs.insert_one({
                "id": new_id(),
                "tenant_id": tenant["id"],
                "actor_user_id": user.get("id"),
                "actor_email": user.get("email"),
                "action": "recurring_job.hard_delete",
                "target_type": "recurring_job_template",
                "target_id": tpl_id,
                "target_snapshot": {
                    k: tpl.get(k) for k in
                    ("id", "customer_id", "service_type", "frequency",
                     "start_date", "end_date", "is_active", "active")
                },
                "future_jobs_cancelled": cancel_res.modified_count,
                "created_at": now_iso(),
            })
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[recurring hard-delete] audit log write failed: {e}")
        return {
            "id": tpl_id,
            "hard_deleted": True,
            "future_jobs_cancelled": cancel_res.modified_count,
        }

    # ── Soft delete branch (existing behavior) ──
    res = await db.recurring_job_templates.update_one(
        {"id": tpl_id, "tenant_id": tenant["id"]},
        {"$set": {"active": False, "is_active": False,
                   "updated_at": now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "template not found")
    return {"id": tpl_id, "active": False, "is_active": False}


async def _stop_template_and_prune_future(tpl_id: str, tenant_id: str) -> Dict[str, Any]:
    """Feb-2026 · Never-end recurrence · Stop action.

    Marks the template inactive, sets ``end_date = today`` (so any
    subsequent regenerate is a no-op), clears ``recurrence_never_ends``
    and removes future *unstarted* occurrences from ``db.jobs``.

    "Unstarted" means ``status == 'scheduled'`` AND
    ``scheduled_date > today``. Jobs the tech already started
    (in-progress, completed, cancelled) are never touched, and today's
    visit is preserved so the crew's route board doesn't lose work
    already loaded. Existing past-dated jobs are preserved.
    """
    today_iso = date.today().isoformat()
    tpl = await db.recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not tpl:
        raise HTTPException(404, "template not found")
    await db.recurring_job_templates.update_one(
        {"id": tpl_id, "tenant_id": tenant_id},
        {"$set": {"active": False,
                    "end_date": today_iso,
                    "recurrence_never_ends": False,
                    "stopped_at": now_iso(),
                    "updated_at": now_iso()}},
    )
    # Remove future, still-scheduled occurrences. Keep today's visit
    # (>= today_iso would nuke it) and preserve started/completed rows.
    del_res = await db.jobs.delete_many({
        "tenant_id": tenant_id,
        "recurring_template_id": tpl_id,
        "status": "scheduled",
        "scheduled_date": {"$gt": today_iso},
    })
    return {
        "template_id": tpl_id,
        "stopped_at": today_iso,
        "removed_future_jobs": del_res.deleted_count,
    }


@router.post("/recurring-jobs/{tpl_id}/stop")
async def stop_recurring(tpl_id: str,
                           user: dict = Depends(require_admin_or_manager),
                           tenant: dict = Depends(get_current_tenant)):
    """Feb-2026 · Never-end recurrence · Stop generating future occurrences.

    Idempotent-ish: calling twice sets end_date to the second call's
    date and returns 0 removed the second time (no more future scheduled
    jobs to prune).
    """
    return await _stop_template_and_prune_future(tpl_id, tenant["id"])


@router.post("/jobs/{jid}/recurrence/stop")
async def stop_recurring_from_job(jid: str,
                                     user: dict = Depends(require_admin_or_manager),
                                     tenant: dict = Depends(get_current_tenant)):
    """Feb-2026 · Job-scoped convenience shim. Resolves the job's
    ``recurring_template_id`` and delegates to the template-stop
    helper. Useful from the Job detail page which only knows the job
    id, not the template id."""
    # Feb-2026 · Note — do NOT pass a projection that includes only
    # ``recurring_template_id``. When the field is absent on the doc,
    # Motor returns ``{}`` and ``if not job:`` becomes truthy → false
    # 404. Read the full doc (cheap — jobs are small) so both the
    # existence check and the ``recurring_template_id`` lookup are
    # reliable.
    job = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]},
    )
    if not job:
        raise HTTPException(404, "job not found")
    tpl_id = job.get("recurring_template_id")
    if not tpl_id:
        raise HTTPException(400, "job is not part of a recurring series")
    return await _stop_template_and_prune_future(tpl_id, tenant["id"])


async def _generate_from_template(tpl: Dict[str, Any], through: date) -> Dict[str, Any]:
    """Idempotent — inserts jobs for occurrences that aren't already
    materialized. Returns {inserted, skipped, dates}."""
    tenant_id = tpl["tenant_id"]
    # Walk from `last_generated_through + 1` OR `start_date`, whichever is later.
    last = _parse_date(tpl.get("last_generated_through"))
    start = _parse_date(tpl.get("start_date")) or date.today()
    anchor = (last + timedelta(days=1)) if last else start
    dates = _next_occurrences(tpl, anchor, through, max_count=200)
    if not dates:
        return {"inserted": 0, "skipped": 0, "dates": []}
    # Look up customer + tech for the payload.
    cust = await db.customers.find_one(
        {"id": tpl.get("customer_id"), "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "address": 1},
    ) or {}
    tech = None
    if tpl.get("assigned_tech_id"):
        tech = await db.users.find_one({"id": tpl["assigned_tech_id"]},
                                          {"_id": 0, "name": 1, "technician_id": 1})
    tech_id = tpl.get("assigned_tech_id")
    tech_name = (tech or {}).get("name") or None
    # Phase H9 · Feb-2026 — crew assignment. When the template
    # carries a crew_id, the generated job carries it too and
    # the F6a scheduling code path (crew_id OR technician_id ∈
    # crew.tech_ids) resolves the specific tech at schedule
    # time. When both are None the job stays unassigned so
    # ``auto-assign`` behavior is preserved.
    crew_id = tpl.get("crew_id")
    crew_name = tpl.get("crew_name")

    price_dollars = round((tpl.get("price_cents") or 0) / 100.0, 2)
    inserted, skipped = 0, 0
    inserted_dates: List[str] = []
    for d in dates:
        iso = d.isoformat()
        try:
            await db.jobs.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "title": tpl.get("service_type") or "Recurring Service",
                "service_type": tpl.get("service_type"),
                "customer_id": tpl.get("customer_id"),
                "customer_name": cust.get("name") or tpl.get("customer_name"),
                "address": cust.get("address") or "",
                "technician_id": tech_id,
                "technician_name": tech_name,
                "crew_id": crew_id,
                "crew_name": crew_name,
                "scheduled_date": iso,
                "status": "scheduled",
                "price": price_dollars,
                "notes": tpl.get("notes") or "",
                "recurring_template_id": tpl["id"],
                "created_at": now_iso(),
            })
            inserted += 1
            inserted_dates.append(iso)
        except Exception as e:
            # Duplicate key = already exists → idempotent skip.
            if "duplicate key" in str(e).lower() or "E11000" in str(e):
                skipped += 1
            else:
                logger.warning(f"recurring insert skipped: {e}")
                skipped += 1
    await db.recurring_job_templates.update_one(
        {"id": tpl["id"], "tenant_id": tenant_id},
        {"$set": {"last_generated_through": dates[-1].isoformat(),
                    "updated_at": now_iso()}},
    )
    return {"inserted": inserted, "skipped": skipped, "dates": inserted_dates}


@router.post("/recurring-jobs/{tpl_id}/generate")
async def generate_now(tpl_id: str,
                         through: Optional[str] = Query(None),
                         user: dict = Depends(require_admin_or_manager),
                         tenant: dict = Depends(get_current_tenant)):
    await _ensure_indexes()
    # Feb-2026 · Recurring Jobs · is_active gate. The manual "Gen
    # 14d" button obeys the same gate the nightly cron uses so
    # dispatchers can't accidentally materialize occurrences for a
    # draft template. The tolerant filter accepts either the new
    # ``is_active: True`` field OR the legacy ``active: True`` for
    # docs that haven't been touched by the backfill migration yet.
    tpl = await db.recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": tenant["id"],
         "$or": [{"is_active": True}, {"active": True, "is_active": {"$exists": False}}]},
        {"_id": 0},
    )
    if not tpl:
        raise HTTPException(404, "template not found or inactive")
    # Also gate on ``start_date`` being set. Unlike the nightly
    # cron (which enforces ``start_date <= today``), the manual
    # ``/generate`` endpoint is a pre-materialization tool, so a
    # start_date in the future is a legitimate use case (the
    # caller supplies ``through`` explicitly). We only reject the
    # missing-start-date case here — same coded detail string.
    _start = _parse_date(tpl.get("start_date"))
    if not _start:
        raise HTTPException(422, {"detail": "start_date_required_for_active"})
    horizon = _parse_date(through) or (date.today() + timedelta(days=14))
    return await _generate_from_template(tpl, horizon)


# ─── APScheduler nightly cron ────────────────────────────────────────
async def run_recurring_job_generator() -> Dict[str, Any]:
    """Iterate every active template across every tenant and generate
    the rolling 2-week horizon.

    Feb-2026 · Recurring Jobs — the ``is_active`` + ``start_date <=
    today`` gate replaces the legacy ``active: True`` filter. Legacy
    docs untouched by the backfill migration (no ``is_active`` field)
    are still picked up when their ``active`` flag is True, so cron
    behavior stays continuous through the migration window.
    """
    await _ensure_indexes()
    today = date.today()
    today_iso = today.isoformat()
    horizon = today + timedelta(days=14)
    total_inserted = 0
    total_skipped = 0
    templates_processed = 0
    _filter = {
        "$and": [
            # New is_active OR legacy active (tolerant of pre-
            # migration docs).
            {"$or": [
                {"is_active": True},
                {"active": True, "is_active": {"$exists": False}},
            ]},
            # Start-date gate — must exist AND be <= today.
            {"start_date": {"$ne": None, "$lte": today_iso}},
        ],
    }
    async for tpl in db.recurring_job_templates.find(_filter, {"_id": 0}):
        try:
            result = await _generate_from_template(tpl, horizon)
            total_inserted += result["inserted"]
            total_skipped += result["skipped"]
            templates_processed += 1
        except Exception as e:
            logger.warning(f"recurring generator error for {tpl.get('id')}: {e}")
    logger.info(
        f"Recurring job generator: templates={templates_processed} "
        f"inserted={total_inserted} skipped={total_skipped}"
    )
    return {"templates_processed": templates_processed,
             "inserted": total_inserted, "skipped": total_skipped}
