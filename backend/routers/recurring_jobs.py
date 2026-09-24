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
from services.query_scope import tenant_scoped_filter

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
    # draft state without immediately materializing jobs.
    #
    # Feb-2026 · P1 Auto-Activate + Instant Generation — flipped
    # the create-default from ``False`` → ``True`` so newly created
    # recurring templates immediately materialize the first 14 days
    # of visits without waiting for the nightly cron. Callers that
    # want a draft template must explicitly send ``is_active: false``
    # in the payload. Legacy DB rows are backfilled to ``True`` by
    # ``services/migrations/recurring_templates_is_active_backfill.py``.
    is_active: bool = True
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
    # Feb-2026 · Recurring Jobs · category taxonomy passthrough.
    # ``service_category_id`` and ``income_category_id`` reference
    # the tenant-scoped master collections (db.service_categories +
    # db.income_categories). Both remain optional so pre-existing
    # templates keep working. The PATCH handler validates each
    # against its collection using the same resolve/active gate as
    # the invoice line-item recategorize flow.
    service_category_id: Optional[str] = None
    income_category_id: Optional[str] = None
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
    # Feb-2026 · Recurring Jobs · category taxonomy passthrough on
    # PATCH. Values must resolve to active rows in the tenant's
    # ``service_categories`` / ``income_categories`` master lists —
    # gate is applied in ``patch_recurring``. Explicit empty string
    # clears the field (same convention as the ``crew_id`` / tech
    # switch above).
    service_category_id: Optional[str] = None
    income_category_id: Optional[str] = None
    # Phase P33 · Feb-2026 — property_id passthrough on PATCH.
    # When present + non-empty, the handler re-validates against
    # ``validate_property_belongs_to_customer`` before persisting
    # (guards against a stale FE that saved a property from the
    # previous customer's list, or a cross-customer property swap).
    property_id: Optional[str] = None
    # Phase P33 · Feb-2026 — customer_id passthrough on PATCH so
    # the two ids can be re-validated together when either changes.
    # Absent (unset) → no change.
    customer_id: Optional[str] = None


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

    # Feb-2026 · Recurring Jobs · end_date ordering. When both dates
    # are supplied on the same body, ``end_date`` MUST be on or after
    # ``start_date`` — the end is inclusive so same-day is a valid
    # single-shot recurrence.
    _start_raw = getattr(body, "start_date", None)
    _end_raw = getattr(body, "end_date", None)
    if _end_raw and _start_raw:
        try:
            _sd = date.fromisoformat(_start_raw)
            _ed = date.fromisoformat(_end_raw)
        except (TypeError, ValueError):
            # Malformed date strings fall through the model's own
            # error path — don't shadow the pydantic message with
            # a 422 here.
            return
        if _ed < _sd:
            raise HTTPException(
                400,
                {"error": "end_date_before_start_date",
                  "start_date": _start_raw, "end_date": _end_raw},
            )


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
    # Phase P33 · Feb-2026 — Property validator ladder. Runs AFTER
    # the customer-exists check so a bogus ``customer_id`` doesn't
    # 400 on "no properties on this customer" (misleading — the
    # customer doesn't exist). Auto-fills ``property_id`` when the
    # customer has exactly one active property AND the payload
    # omitted it (defense in depth against a stale FE that missed
    # the client-side auto-select).
    from services.customer_properties import (
        resolve_recurring_property_payload,
    )
    body.property_id = await resolve_recurring_property_payload(
        tenant["id"], body.customer_id, body.property_id,
        context="create_recurring",
    )
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
    # Feb-2026 · P1 Auto-Activate + Instant Generation — fire the
    # 14-day inline generator when the template is being created
    # in the active state. Fail-open: a generation error must not
    # block the create response (log a warning, return the
    # persisted template anyway). The start-date guard lives inside
    # ``_instant_generate_for_template``.
    generated_count = 0
    skipped_no_start_date = False
    if doc.get("is_active"):
        try:
            _gen = await _instant_generate_for_template(doc)
            generated_count = int(_gen.get("inserted") or 0)
            skipped_no_start_date = bool(_gen.get("skipped_no_start_date"))
        except Exception as _gen_exc:                            # noqa: BLE001
            logger.warning(
                "[recurring_job.instant_generation_failed] template=%s "
                "op=create error=%s", doc.get("id"), _gen_exc,
            )
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
    # Feb-2026 · P1 Auto-Activate — surface the instant-generation
    # telemetry so the FE can toast "N visits scheduled" without a
    # follow-up call.
    doc["generated_count"] = generated_count
    doc["skipped_no_start_date"] = skipped_no_start_date
    return doc


@router.get("/recurring-jobs")
async def list_recurring(active: Optional[bool] = Query(None),
                          status: Optional[str] = Query(
                              None,
                              description=(
                                  "Phase P18 · Feb-2026 — filter by "
                                  "status: 'active' | 'paused' | None. "
                                  "None returns everything (backward-"
                                  "compat with legacy callers using "
                                  "the ``active`` bool query param)."
                              ),
                          ),
                          user: dict = Depends(require_admin_or_manager),
                          tenant: dict = Depends(get_current_tenant)):
    """List recurring-job templates for the current tenant.

    Phase P18 · Feb-2026 — Active/Paused tab support.
      * ``status=active``  → returns rows where the canonical
        ``is_active`` field is True (OR the legacy ``active`` field
        is True on rows that predate the CHEM2-era backfill).
      * ``status=paused``  → the inverse.
      * ``status`` omitted (or ``None``) → no status filter.  The
        legacy ``active: Optional[bool]`` param remains supported
        so any UI still on the pre-P18 wire contract keeps working;
        ``status`` wins when both are present.
      * Response ADDITIVELY carries ``counts = {active, paused,
        total}`` so the frontend tab strip can render badges
        without a second round-trip.
    """
    # ── Phase P18 · Feb-2026 — active predicate ────────────────────
    # Every row's "is this active?" answer is either:
    #   1. ``is_active == True``                (post-backfill), or
    #   2. ``is_active`` missing AND ``active == True``  (legacy).
    # The paused predicate is the strict inverse — anything else.
    _ACTIVE_OR = [
        {"is_active": True},
        {"is_active": {"$exists": False}, "active": True},
    ]
    _PAUSED_OR = [
        {"is_active": False},
        {"is_active": {"$exists": False},
         "$or": [{"active": False}, {"active": {"$exists": False}}]},
    ]

    or_clauses: list = []
    if status == "active":
        or_clauses.append(_ACTIVE_OR)
    elif status == "paused":
        or_clauses.append(_PAUSED_OR)
    elif status is None and active is True:
        or_clauses.append(_ACTIVE_OR)
    elif status is None and active is False:
        or_clauses.append(_PAUSED_OR)
    # else: no status filter — return everything.

    # Phase P18 · Feb-2026 — funnel every query through
    # ``tenant_scoped_filter`` so the new active/paused ``$or``
    # can't collide with soft-delete via dict-spread merge.
    q = tenant_scoped_filter(tenant["id"], *or_clauses)

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

    # Phase R2 · Feb-2026 — attach the extra customer fields the
    # client-side search filters on (company_name, email, phone).
    # Batch fetch so the row count doesn't fan out into N+1 queries.
    cust_ids = list({r.get("customer_id") for r in rows if r.get("customer_id")})
    cust_map: Dict[str, Dict[str, Any]] = {}
    if cust_ids:
        async for c in db.customers.find(
            {"tenant_id": tenant["id"], "id": {"$in": cust_ids}},
            {"_id": 0, "id": 1, "company_name": 1, "email": 1, "phone": 1},
        ):
            cust_map[c["id"]] = c
    for r in rows:
        c = cust_map.get(r.get("customer_id") or "") or {}
        # Never overwrite an existing denormalized value on the row —
        # some rows historically carry ``customer_name`` at insert time.
        r.setdefault("customer_company_name", c.get("company_name") or "")
        r.setdefault("customer_email", c.get("email") or "")
        r.setdefault("customer_phone", c.get("phone") or "")

    # ── Phase P18 · Feb-2026 — counts (single aggregate) ───────────
    # ``$ifNull`` picks ``is_active`` when present, else falls back
    # to the legacy ``active`` field.  Compare to True to bucket the
    # row.  One round-trip regardless of tenant size.
    counts: Dict[str, int] = {"active": 0, "paused": 0, "total": 0}
    counts_pipeline = [
        {"$match": {"tenant_id": tenant["id"]}},
        {"$group": {
            "_id": {
                "$cond": [
                    {"$eq": [
                        True,
                        {"$ifNull": ["$is_active", "$active"]},
                    ]},
                    "active",
                    "paused",
                ],
            },
            "count": {"$sum": 1},
        }},
    ]
    async for c in db.recurring_job_templates.aggregate(counts_pipeline):
        bucket = c.get("_id")
        cnt = int(c.get("count") or 0)
        if bucket in ("active", "paused"):
            counts[bucket] = cnt
        counts["total"] += cnt

    return {"items": rows, "count": len(rows), "counts": counts}


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
    # Feb-2026 · Recurring Jobs · category taxonomy passthrough.
    # Validate + normalize the two optional category fields against
    # the master collections before hitting Mongo. Empty string
    # clears the field on the doc via ``$set: None``.
    _CATEGORY_KEYS = {
        "income_category_id": "income_categories",
        "service_category_id": "service_categories",
    }
    _category_resolved: Dict[str, Any] = {}
    for _field, _coll in _CATEGORY_KEYS.items():
        if _field not in raw:
            continue
        _val = raw[_field]
        if isinstance(_val, str):
            _val = _val.strip()
            if len(_val) > 80:
                raise HTTPException(
                    422, {"error": f"{_field}_too_long", "max_len": 80},
                )
            if "<" in _val or ">" in _val:
                raise HTTPException(
                    422, {"error": f"{_field}_no_html"},
                )
        if not _val:
            # Empty string clears — stamp None on the doc.
            raw[_field] = None
            _category_resolved[_field] = None
            continue
        _cat = await db[_coll].find_one(
            {"id": _val, "tenant_id": tenant["id"],
              "is_archived": {"$ne": True}},
            {"_id": 0, "id": 1, "name": 1},
        )
        if not _cat:
            # Phase P4 · Feb-2026 — align to the P4 brief:
            # HTTP 422 with ``code`` (not ``error``) and a
            # ``<field>_invalid`` shape so the frontend can key
            # on it deterministically. The response body keeps
            # ``attempted`` + ``collection`` so ops can trace
            # the offending id in a Sentry event.
            _code = ("service_category_invalid"
                      if _field == "service_category_id"
                      else "income_category_invalid")
            raise HTTPException(
                422,
                {"code": _code,
                  "field": _field,
                  "attempted": _val,
                  "collection": _coll},
            )
        raw[_field] = _cat["id"]
        _category_resolved[_field] = _cat
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
    #
    # Feb-2026 · Recurring Jobs · category taxonomy — same treatment
    # for ``income_category_id`` / ``service_category_id`` so an
    # explicit clear (empty-string PATCH) actually writes ``None``.
    _ASSIGN_KEYS = {"assigned_tech_id", "crew_id"}
    # Phase P33 · Feb-2026 — property_id must survive as explicit
    # None in the ``$set`` so the resolve-ladder's auto-clear (zero
    # properties + legacy allow-through) actually erases a stale id
    # rather than being silently dropped by the ``v is not None``
    # filter below.
    _CLEARABLE = _ASSIGN_KEYS | set(_CATEGORY_KEYS.keys()) | {"property_id"}
    updates: Dict[str, Any] = {
        k: v for k, v in raw.items()
        if v is not None or k == "active" or k == "is_active" or k in _CLEARABLE
    }
    # If the caller supplied both assignment fields with non-None
    # values, reject before writing.
    _reject_double_assignment(
        assigned_tech_id=updates.get("assigned_tech_id"),
        crew_id=updates.get("crew_id"),
    )
    # Phase P33 · Feb-2026 — Property validator on PATCH. Fires when
    # either ``customer_id`` or ``property_id`` is in the patch set,
    # so a legitimate "swap the property to a new one" AND a
    # "move the template to a different customer" both re-validate
    # ownership. The validator runs against the FINAL pair — the
    # incoming ``customer_id`` if present, otherwise the pre-image's
    # ``customer_id``.
    _touches_property = ("property_id" in updates
                          or "customer_id" in updates)
    if _touches_property:
        _existing = await db.recurring_job_templates.find_one(
            {"id": tpl_id, "tenant_id": tenant["id"]},
            {"_id": 0, "customer_id": 1, "property_id": 1},
        )
        if not _existing:
            raise HTTPException(404, "template not found")
        _effective_cid = updates.get("customer_id") or _existing.get("customer_id")
        _effective_pid = (
            updates["property_id"] if "property_id" in updates
            else _existing.get("property_id")
        )
        if _effective_cid:
            from services.customer_properties import (
                resolve_recurring_property_payload,
            )
            _final_pid = await resolve_recurring_property_payload(
                tenant["id"], _effective_cid, _effective_pid,
                context="patch_recurring",
            )
            # Stamp the resolved (possibly auto-filled) id back on
            # the write set so the DB doc reflects the validator's
            # normalization.
            updates["property_id"] = _final_pid
    # If ``crew_id`` is being SET (non-None), resolve it and stamp
    # the denorm name. If cleared to None, drop the denorm too.
    if "crew_id" in updates:
        if updates["crew_id"]:
            crew = await _resolve_crew_ref(tenant["id"], updates["crew_id"])
            updates["crew_name"] = (crew or {}).get("name")
        else:
            updates["crew_name"] = None
    # Feb-2026 · Recurring Jobs · category taxonomy — stamp denorm
    # names on the doc so the list endpoint can render labels
    # without a per-row category-collection point-lookup.
    for _field, _cat in _category_resolved.items():
        _denorm = _field.replace("_id", "_name")
        updates[_denorm] = (_cat or {}).get("name") if _cat else None
    # Feb-2026 · Never-end intent overrides end_date on patch too.
    if updates.get("recurrence_never_ends") is True:
        updates["end_date"] = None
    updates["updated_at"] = now_iso()
    # Feb-2026 · Recurring Jobs · category audit. Fetch the pre-
    # image (once, projected) so the audit diff has real ``before``
    # values. Only fires when a category field is actually part of
    # the write set.
    #
    # Feb-2026 · P1 Auto-Activate — we ALSO need the pre-image
    # ``is_active`` to detect the False→True transition that fires
    # inline generation. Merge both projections into a single
    # lookup when either is required.
    _needs_category_pre = any(k in updates for k in _CATEGORY_KEYS)
    _needs_is_active_pre = "is_active" in updates
    _pre_image: Dict[str, Any] = {}
    if _needs_category_pre or _needs_is_active_pre:
        _pre_image = await db.recurring_job_templates.find_one(
            {"id": tpl_id, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1,
              "income_category_id": 1, "income_category_name": 1,
              "service_category_id": 1, "service_category_name": 1,
              "is_active": 1},
        ) or {}
    res = await db.recurring_job_templates.update_one(
        {"id": tpl_id, "tenant_id": tenant["id"]},
        {"$set": updates},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "template not found")
    if _needs_category_pre and _pre_image:
        await _write_recurring_category_audit(
            tenant_id=tenant["id"], tpl_id=tpl_id,
            actor=user, before=_pre_image, updates=updates,
        )
    # ── P55 · Feb-2026 — Category sync fan-out ──
    # When a category field was in the write set, propagate the
    # new value to every linked UNPAID Invoice via the
    # ``sync_recurring_template_to_children`` orchestrator. Jobs
    # are DELIBERATELY NOT updated (Q1/Option B in P55 · they
    # don't carry category fields today). If a category id was
    # deleted after the PATCH validation but before the
    # orchestrator's own name-resolve, the orchestrator raises
    # ``CategorySyncNameLookupError`` — we translate to HTTP 422
    # with a specific code so the caller can retry with the
    # correct id.
    if _needs_category_pre and res.matched_count > 0:
        from services.category_sync import (
            sync_recurring_template_to_children,
            CategorySyncNameLookupError,
        )
        _sync_kwargs: Dict[str, Any] = {"origin": "recurring_template_edit"}
        if "income_category_id" in updates:
            _sync_kwargs["income_category_id"] = updates.get("income_category_id")
        if "service_category_id" in updates:
            _sync_kwargs["service_category_id"] = updates.get("service_category_id")
        try:
            await sync_recurring_template_to_children(
                tenant_id=tenant["id"],
                recurring_job_id=tpl_id,
                actor_id=(user or {}).get("id"),
                **_sync_kwargs,
            )
        except CategorySyncNameLookupError as _cs_exc:
            raise HTTPException(
                422,
                {"code": "category_deleted_after_source_write",
                 "category_id": _cs_exc.category_id,
                 "collection": _cs_exc.collection},
            )
        except Exception as _cs_exc:                       # noqa: BLE001
            # Best-effort fan-out — the template write itself
            # succeeded; a fan-out crash is logged and swallowed
            # so the PATCH response reflects the source-of-truth
            # state. Ops can re-run via a bulk backfill if the
            # sync repeatedly fails on a specific tenant.
            logger.warning(
                "[category_sync.recurring→invoices.failed] "
                "template=%s error=%s", tpl_id, _cs_exc,
            )
    _final = await db.recurring_job_templates.find_one(
        {"id": tpl_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    # Feb-2026 · P1 Auto-Activate + Instant Generation — PATCH fires
    # inline generation ONLY when ``is_active`` transitions
    # False→True (or unset→True). If the PATCH doesn't touch
    # ``is_active`` OR sets it to False, no generation runs.
    generated_count = 0
    skipped_no_start_date = False
    _before_is_active = _pre_image.get("is_active")
    _incoming_is_active = updates.get("is_active")
    if (_needs_is_active_pre
        and _incoming_is_active is True
        and _before_is_active is not True):
        try:
            _gen = await _instant_generate_for_template(_final or {})
            generated_count = int(_gen.get("inserted") or 0)
            skipped_no_start_date = bool(_gen.get("skipped_no_start_date"))
        except Exception as _gen_exc:                            # noqa: BLE001
            logger.warning(
                "[recurring_job.instant_generation_failed] template=%s "
                "op=patch error=%s", tpl_id, _gen_exc,
            )
    # ── Phase P18 · Feb-2026 — Pause side-effect ──
    # When ``is_active`` transitions True→False, cancel every FUTURE
    # ``pending`` / ``scheduled`` visit derived from this template
    # AND snapshot each into ``deletion_audit`` (resource_type="job",
    # shared ``bulk_op_id``) so a future Resume flow — or a forensic
    # audit — has the pre-cancel state.
    #
    # Soft-cancel (status flip + reason stamp), NEVER hard-delete —
    # preserves the audit trail on the job docs themselves and keeps
    # any downstream analytics happy.
    cancelled_visit_count = 0
    if (_needs_is_active_pre
        and _incoming_is_active is False
        and _before_is_active is True):
        cancelled_visit_count = await _cancel_future_visits_on_pause(
            tenant_id=tenant["id"], tpl_id=tpl_id, actor=user,
        )
    if _final is not None:
        _final["generated_count"] = generated_count
        _final["skipped_no_start_date"] = skipped_no_start_date
        _final["cancelled_visit_count"] = cancelled_visit_count
    return _final


# ─── Phase P18 · Feb-2026 · Pause side-effect helper ─────────────────
async def _cancel_future_visits_on_pause(
    *, tenant_id: str, tpl_id: str, actor: Dict[str, Any],
) -> int:
    """Cancel every FUTURE ``pending`` / ``scheduled`` visit derived
    from ``tpl_id``.  Called from :func:`patch_recurring` when the
    template's ``is_active`` transitions True → False.

    Behaviour:
      * Future-visit predicate — ``scheduled_date >= <today_iso>``
        OR ``scheduled_start >= <now_utc>``.  The generator persists
        recurring visits with ``scheduled_date`` (a ``YYYY-MM-DD``
        string) and NO ``scheduled_start`` field, so filtering on
        ``scheduled_start`` alone would silently miss every generated
        occurrence.  Manually-scheduled jobs (which populate
        ``scheduled_start`` as an ISO datetime) also match.  Past
        visits are NEVER touched (they're either done, in-progress,
        or already historic — cancelling them retroactively would
        corrupt the billing + KPI trail).
      * ``status IN ("pending", "scheduled")`` — completed /
        cancelled / on-hold visits are also skipped.
      * Update stamps: ``status="cancelled"``, ``cancelled_at=<now>``,
        ``cancelled_reason="recurring_paused"``.
      * One :func:`write_deletion_audit_entry` row per affected job
        with a SHARED ``bulk_op_id`` so the whole pause action is
        queryable as a group.
      * NO hard-delete — the ``jobs`` row stays in the collection
        with its new ``cancelled`` status so a future Resume flow
        can restore cleanly (deferred, tracked in P18 wrap-up).

    Filter uses ``tenant_scoped_filter`` to prevent any ``$or``
    clobber via dict-spread merge.  Never raises — a per-audit-write
    failure is logged but doesn't abort the pause path.

    Returns the number of visits actually flipped (matches the
    Mongo ``update_many.modified_count``).
    """
    import uuid
    from routers.deletion_audit import write_deletion_audit_entry

    now_dt = datetime.now(timezone.utc)
    now_iso_str = now_dt.isoformat()
    today_iso = now_dt.date().isoformat()
    bulk_op_id = str(uuid.uuid4())

    # Build the filter via ``tenant_scoped_filter``.  The date/
    # datetime disjunction MUST flow through the helper because a
    # naive dict-spread with ``_nd()`` (the soft-delete OR) would
    # clobber it — this is the exact idiom the P12 audit called out.
    future_q = tenant_scoped_filter(
        tenant_id,
        [
            {"scheduled_date": {"$gte": today_iso}},
            {"scheduled_start": {"$gte": now_iso_str}},
        ],
        recurring_template_id=tpl_id,
        status={"$in": ["pending", "scheduled"]},
    )

    # Snapshot first so the deletion_audit row carries the pre-flip
    # state.  Only ``id`` needs to survive on the projection side;
    # the ``snapshot`` uses the full doc minus ``_id`` (audit
    # helper's own scrub).
    affected = await db.jobs.find(future_q, {"_id": 0}).to_list(5000)
    if not affected:
        return 0

    # Update every match in ONE round-trip.  ``modified_count`` is
    # authoritative even when idempotent flips happen (defensive).
    upd = await db.jobs.update_many(
        future_q,
        {"$set": {
            "status": "cancelled",
            "cancelled_at": now_iso_str,
            "cancelled_reason": "recurring_paused",
            "updated_at": now_iso_str,
        }},
    )

    # Write one deletion_audit per affected job.  Best-effort — a
    # write failure logs + continues so the pause never blocks on a
    # side collection outage.
    for job_doc in affected:
        try:
            await write_deletion_audit_entry(
                tenant_id=tenant_id,
                resource_type="job",
                resource_id=str(job_doc.get("id") or job_doc.get("_id") or ""),
                user=actor or {},
                snapshot=job_doc,
                deletion_reason="recurring_paused",
                bulk_op_id=bulk_op_id,
            )
        except Exception:                                          # noqa: BLE001
            logger.exception(
                "[recurring.pause.audit] audit write failed for "
                "job=%s template=%s tenant=%s bulk_op_id=%s",
                job_doc.get("id"), tpl_id, tenant_id, bulk_op_id,
            )

    logger.info(
        "[recurring.pause] template=%s tenant=%s cancelled_visits=%s "
        "bulk_op_id=%s",
        tpl_id, tenant_id, int(upd.modified_count or 0), bulk_op_id,
    )
    return int(upd.modified_count or 0)


# Feb-2026 · Recurring Jobs · category audit. Writes ONE
# ``audit_logs`` row per PATCH that changes at least one category
# field, mirroring the ``line_item.recategorize`` shape used by
# ``routers/income_categories.py`` (grep-consistency).
async def _write_recurring_category_audit(
    *, tenant_id: str, tpl_id: str, actor: Dict[str, Any],
    before: Dict[str, Any], updates: Dict[str, Any],
) -> None:
    diff: Dict[str, Dict[str, Any]] = {}
    for field in ("income_category_id", "income_category_name",
                  "service_category_id", "service_category_name"):
        if field in updates and before.get(field) != updates.get(field):
            diff[field] = {"before": before.get(field),
                            "after": updates.get(field)}
    if not diff:
        return
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "event": "recurring_job.recategorize",
            "recurring_template_id": tpl_id,
            "actor_id": (actor or {}).get("id"),
            "actor_email": (actor or {}).get("email"),
            "actor_role": ((actor or {}).get("role") or "").lower(),
            "diff": diff,
            "created_at": now_iso(),
        })
    except Exception:                                              # noqa: BLE001
        logger.exception(
            "[recurring-jobs.audit] insert failed for template=%s",
            tpl_id,
        )


# ─── Phase R1 · Feb-2026 · Recurring-Jobs Bulk Hard Delete ────────────
#
# Extracted from ``delete_recurring(hard=True)`` so the per-row + bulk
# endpoints share ONE removal + audit path.  Never raises HTTPException
# so the bulk loop can aggregate per-id status without one bad id
# short-circuiting the response.
async def _hard_delete_recurring_job(
    *,
    tpl_id: str,
    actor: Dict[str, Any],
    tenant_id: str,
    today_anchor: str,
) -> Dict[str, Any]:
    """Hard-delete one recurring template + cancel its future visits.

    Parameters
    ----------
    tpl_id
        Recurring-job template id.
    actor
        The authenticated user dict — used for the audit trail.
    tenant_id
        Owning tenant.  Rows belonging to a different tenant return
        ``status = "forbidden"`` and are NOT touched.
    today_anchor
        ISO date string.  Every child job whose ``scheduled_date >=
        today_anchor`` is cancelled.  Callers preserving the pre-R1
        strictly-greater semantics pass tomorrow's date; the bulk
        endpoint passes ``date.today().isoformat()`` per the phase
        brief.

    Returns
    -------
    dict shaped as::

        {"recurring_job_id": str,
         "status": "deleted" | "not_found" | "forbidden" | "error",
         "future_visits_deleted": int,
         "error"?: str}
    """
    try:
        tpl = await db.recurring_job_templates.find_one(
            {"id": tpl_id}, {"_id": 0},
        )
        if not tpl:
            return {"recurring_job_id": tpl_id,
                     "status": "not_found",
                     "future_visits_deleted": 0}
        if tpl.get("tenant_id") != tenant_id:
            return {"recurring_job_id": tpl_id,
                     "status": "forbidden",
                     "future_visits_deleted": 0}
        cancel_res = await db.jobs.update_many(
            {
                "tenant_id": tenant_id,
                "recurring_template_id": tpl_id,
                "status": "scheduled",
                "scheduled_date": {"$gte": today_anchor},
            },
            {"$set": {"status": "cancelled",
                       "cancelled_at": now_iso(),
                       "cancelled_reason": "recurring_template_hard_deleted",
                       "updated_at": now_iso()}},
        )
        future_visits_deleted = int(cancel_res.modified_count or 0)
        await db.recurring_job_templates.delete_one(
            {"id": tpl_id, "tenant_id": tenant_id},
        )
        try:
            await db.audit_logs.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "actor_user_id": actor.get("id"),
                "actor_email": actor.get("email"),
                "action": "recurring_job.hard_delete",
                "target_type": "recurring_job_template",
                "target_id": tpl_id,
                "target_snapshot": {
                    k: tpl.get(k) for k in
                    ("id", "customer_id", "service_type", "frequency",
                     "start_date", "end_date", "is_active", "active")
                },
                "future_jobs_cancelled": future_visits_deleted,
                "created_at": now_iso(),
            })
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"[recurring hard-delete] audit log write failed: {e}")
        return {"recurring_job_id": tpl_id,
                 "status": "deleted",
                 "future_visits_deleted": future_visits_deleted}
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"[recurring hard-delete] id={tpl_id} unexpected error: {e}")
        return {"recurring_job_id": tpl_id,
                 "status": "error",
                 "future_visits_deleted": 0,
                 "error": str(e)}


class _BulkDeleteIn(BaseModel):
    recurring_job_ids: List[str] = Field(..., min_items=1, max_items=200)


@router.post("/recurring-jobs/bulk-delete")
async def bulk_hard_delete_recurring(
    body: _BulkDeleteIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase R1 · Feb-2026 — bulk hard-delete recurring templates.

    Best-effort per-id: verifies tenant ownership, cancels every
    future-scheduled child job (``scheduled_date >= today``), removes
    the template row, and emits an audit-log entry.  Never raises
    on partial failures — each id gets its own status row and the
    caller sees an aggregate summary.

    Auth: ``require_admin`` (accepts ``admin`` / ``super_admin`` /
    ``owner`` per ``utils.require_admin``).  Non-admin callers get
    403 before this handler ever runs.
    """
    # Preserve caller order + de-dupe silently — repeat ids in a
    # single call would double-count summary numbers otherwise.
    ids_seen: set = set()
    ordered_ids: List[str] = []
    for tid in body.recurring_job_ids:
        if tid and tid not in ids_seen:
            ids_seen.add(tid)
            ordered_ids.append(tid)

    today_iso = date.today().isoformat()
    results: List[Dict[str, Any]] = []
    for tid in ordered_ids:
        results.append(await _hard_delete_recurring_job(
            tpl_id=tid, actor=user, tenant_id=tenant["id"],
            today_anchor=today_iso,
        ))

    templates_deleted = sum(1 for r in results if r["status"] == "deleted")
    future_visits_deleted = sum(
        int(r.get("future_visits_deleted") or 0) for r in results)
    errors = sum(1 for r in results
                    if r["status"] in ("error", "forbidden", "not_found"))
    return {
        "results": results,
        "summary": {
            "templates_deleted": templates_deleted,
            "future_visits_deleted": future_visits_deleted,
            "errors": errors,
        },
    }


# Feb-2026 · P1 Auto-Activate + Bulk Activate + Instant Generation.
# Batch cap of 100 is intentionally strict — payloads over 100 ids
# return 400 so the client MUST slice + call in batches. A WARNING
# log fires whenever a request hits the cap so ops can eyeball
# whether the cap needs raising.
_BULK_ACTIVATE_MAX = 100


class _BulkActivateIn(BaseModel):
    recurring_job_ids: List[str] = Field(..., min_items=1)


@router.post("/recurring-jobs/bulk-activate")
async def bulk_activate_recurring(
    body: _BulkActivateIn,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """Feb-2026 · P1 — bulk-activate recurring templates and fire
    the 14-day instant generator on each one.

    Per-id semantics:
      * ``activated``        — template was not previously
        ``is_active=True``; both ``active`` and ``is_active`` are
        stamped True and instant generation runs.
      * ``already_active``   — template was already
        ``is_active=True``; the fields are re-stamped (idempotent)
        and instant generation still runs so newly-eligible
        occurrences since the last cron get filled in.
      * ``failed``           — the template couldn't be found under
        the caller's tenant, or generation raised. ``error`` carries
        the reason.

    Every result row carries ``generated_count`` and
    ``skipped_no_start_date`` so operators see honest telemetry.
    """
    ids_seen: set = set()
    ordered_ids: List[str] = []
    for tid in body.recurring_job_ids:
        if tid and tid not in ids_seen:
            ids_seen.add(tid)
            ordered_ids.append(tid)

    if len(ordered_ids) > _BULK_ACTIVATE_MAX:
        logger.warning(
            "[recurring_job.bulk_activate.batch_too_large] tenant=%s "
            "received=%d cap=%d",
            tenant.get("id"), len(ordered_ids), _BULK_ACTIVATE_MAX,
        )
        raise HTTPException(400, {
            "error": "batch_too_large",
            "max": _BULK_ACTIVATE_MAX,
            "received": len(ordered_ids),
        })

    results: List[Dict[str, Any]] = []
    activated = 0
    already_active = 0
    failed = 0
    for tid in ordered_ids:
        tpl = await db.recurring_job_templates.find_one(
            {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0},
        )
        if not tpl:
            failed += 1
            results.append({
                "id": tid, "status": "failed",
                "generated_count": 0, "skipped_no_start_date": False,
                "error": "not_found",
            })
            continue
        was_active = tpl.get("is_active") is True
        # Stamp both ``active`` + ``is_active`` (idempotent). The
        # legacy ``active`` flag is kept in sync so downstream code
        # gated on either field sees a consistent view.
        try:
            await db.recurring_job_templates.update_one(
                {"id": tid, "tenant_id": tenant["id"]},
                {"$set": {"active": True, "is_active": True,
                          "updated_at": now_iso()}},
            )
            # Refresh the in-memory doc so the generator sees the
            # freshly-stamped active flags.
            tpl["active"] = True
            tpl["is_active"] = True
        except Exception as _upd_exc:                            # noqa: BLE001
            failed += 1
            results.append({
                "id": tid, "status": "failed",
                "generated_count": 0, "skipped_no_start_date": False,
                "error": f"update_failed: {_upd_exc}",
            })
            continue
        # Fire the 14-day instant generator. Fail-open — a
        # per-template generation error must NOT block the rest of
        # the batch; the row status stays ``activated`` / ``already_
        # active`` (the flag flip succeeded) but ``error`` carries
        # the exception detail.
        gen_count = 0
        skipped_no_start_date = False
        gen_error: Optional[str] = None
        try:
            _gen = await _instant_generate_for_template(tpl)
            gen_count = int(_gen.get("inserted") or 0)
            skipped_no_start_date = bool(_gen.get("skipped_no_start_date"))
        except Exception as _gen_exc:                            # noqa: BLE001
            logger.warning(
                "[recurring_job.instant_generation_failed] template=%s "
                "op=bulk_activate error=%s", tid, _gen_exc,
            )
            gen_error = str(_gen_exc)
        row: Dict[str, Any] = {
            "id": tid,
            "status": "already_active" if was_active else "activated",
            "generated_count": gen_count,
            "skipped_no_start_date": skipped_no_start_date,
        }
        if gen_error is not None:
            row["error"] = gen_error
        results.append(row)
        if was_active:
            already_active += 1
        else:
            activated += 1

    return {
        "activated": activated,
        "already_active": already_active,
        "failed": failed,
        "results": results,
    }


# Feb-2026 · P54 · Recurring Jobs · Bulk-Update Categories.
# Batch cap kept in-file next to ``_BULK_ACTIVATE_MAX`` (=100) per
# the discovered per-endpoint constant pattern. The 100 ceiling
# reflects the P55 fan-out cost — each bulk-update-categories row
# fires ``sync_recurring_template_to_children`` which walks every
# linked unpaid child invoice for that template. Raising the cap
# without also load-testing the fan-out would risk long-running
# request handlers on tenants with dense recurring schedules.
_BULK_UPDATE_CATEGORIES_MAX = 100


class _BulkUpdateCategoriesIn(BaseModel):
    """P54 · Feb-2026 — Bulk category-edit payload.

    Both category fields are ``Optional`` at the type level so the
    payload can carry only one, only the other, or both.  Semantics
    for each field (using Pydantic v2 ``model_fields_set`` to
    distinguish JSON-absent from JSON-null):

      * field NOT in ``model_fields_set`` (JSON key absent)   → unchanged
      * field present with a non-empty string value           → validate + apply
      * field present with ``None`` or an empty string        → unchanged
        (belt-and-suspenders — the FE omits the key for "Unchanged"
         but we defend against a stale client that sends ``null``)
    """
    ids: List[str] = Field(..., min_length=1)
    service_category_id: Optional[str] = None
    income_category_id: Optional[str] = None


@router.post("/recurring-jobs/bulk-update-categories")
async def bulk_update_categories_recurring(
    body: _BulkUpdateCategoriesIn,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase P54 · Feb-2026 — Bulk-edit service + income category
    across many recurring templates in one call.

    Consumes the P55 ``sync_recurring_template_to_children``
    orchestrator per updated row so every linked unpaid child
    invoice picks up the new taxonomy id without a manual PATCH per
    template.

    Per-id status (mirroring ``bulk_activate_recurring`` telemetry):
      * ``updated``          — the template's category fields
        differed from the incoming target; the write landed; the
        P55 sync fan-out fired successfully.
      * ``already_current``  — every incoming field already matched
        the on-disk value. Idempotent no-op: no write, no sync, no
        audit row.
      * ``failed``           — the template couldn't be found under
        the caller's tenant (out-of-tenant ids land here too, per
        the Q2 honest-telemetry precedent), OR the P55 sync raised
        ``CategorySyncNameLookupError`` (a category was deleted
        between our validation and the orchestrator's own
        name-resolve — the template write already landed, so the
        caller sees a partial-apply state on that row).

    Rejects with 400:
      * ``batch_too_large`` when ``len(ids) > 100``.
      * ``no_category_fields_set`` when neither category field
        resolves to a non-empty value.

    Rejects with 422 (payload-level, before any per-row loop starts):
      * ``<field>_too_long`` when the id string is > 80 chars.
      * ``<field>_no_html`` when the id string contains ``<`` or ``>``.
      * ``service_category_invalid`` / ``income_category_invalid``
        when the id doesn't resolve to an active row on the caller's
        tenant. Payload-level so the FE can key on ``code`` before
        any partial writes happen — matches the single-item PATCH
        contract at ``recurring_jobs.py :828-849``.

    Response:
      ``{"updated": int, "already_current": int, "failed": int,
         "sync_result_summary": {"child_invoices_updated": int,
                                  "child_invoices_skipped_paid": int,
                                  "child_invoices_skipped_loop": int,
                                  "child_error_rows": int},
         "results": [{"id", "status", "error"?}]}``
    """
    # Normalize + dedupe the incoming ids so a repeat id in one call
    # can't double-count summary numbers or fire the sync twice.
    ids_seen: set = set()
    ordered_ids: List[str] = []
    for tid in body.ids:
        if tid and tid not in ids_seen:
            ids_seen.add(tid)
            ordered_ids.append(tid)

    # Batch cap — mirror bulk-activate's WARNING log + 400 shape.
    if len(ordered_ids) > _BULK_UPDATE_CATEGORIES_MAX:
        logger.warning(
            "[recurring_job.bulk_update_categories.batch_too_large] "
            "tenant=%s received=%d cap=%d",
            tenant.get("id"), len(ordered_ids),
            _BULK_UPDATE_CATEGORIES_MAX,
        )
        raise HTTPException(400, {
            "error": "batch_too_large",
            "max": _BULK_UPDATE_CATEGORIES_MAX,
            "received": len(ordered_ids),
        })

    # Which fields did the caller explicitly send? Pydantic v2 —
    # ``model_fields_set`` reflects the JSON keys present at parse
    # time so we can distinguish "omitted" from "sent as null".
    _sent_fields = body.model_fields_set

    _CATEGORY_KEYS = {
        "income_category_id": "income_categories",
        "service_category_id": "service_categories",
    }
    # Resolve each caller-sent field ONCE up-front before the
    # per-row loop begins. This mirrors the single-item PATCH
    # (recurring_jobs.py :809-851) — validation raises payload-level
    # 422 on the first bad id so we never enter the loop with a
    # half-usable payload.
    resolved_by_field: Dict[str, Dict[str, Any]] = {}
    for _field, _coll in _CATEGORY_KEYS.items():
        if _field not in _sent_fields:
            continue
        _val = getattr(body, _field)
        if _val is None:
            # JSON ``null`` on this field — treat as "unchanged"
            # (Q3/A · belt-and-suspenders vs a stale client).
            continue
        _val = str(_val).strip()
        if not _val:
            # Empty string — unchanged; no clear support in bulk.
            continue
        if len(_val) > 80:
            raise HTTPException(
                422, {"error": f"{_field}_too_long", "max_len": 80},
            )
        if "<" in _val or ">" in _val:
            raise HTTPException(
                422, {"error": f"{_field}_no_html"},
            )
        _cat = await db[_coll].find_one(
            {"id": _val, "tenant_id": tenant["id"],
              "is_archived": {"$ne": True}},
            {"_id": 0, "id": 1, "name": 1},
        )
        if not _cat:
            _code = ("service_category_invalid"
                     if _field == "service_category_id"
                     else "income_category_invalid")
            raise HTTPException(
                422,
                {"code": _code, "field": _field,
                  "attempted": _val, "collection": _coll},
            )
        resolved_by_field[_field] = _cat

    if not resolved_by_field:
        raise HTTPException(
            400, {"error": "no_category_fields_set",
                    "hint": ("at least one of ``service_category_id`` "
                            "or ``income_category_id`` must be present "
                            "with a non-empty value")},
        )

    # Import the P55 orchestrator once — the per-row loop fires it
    # per updated template. Origin marker ``bulk_recurring_edit`` is
    # verified NOT in ``_SKIP_TABLE`` by the P54 test suite's
    # ``test_bulk_edit_origin_not_in_skip_set`` guard.
    from services.category_sync import (
        sync_recurring_template_to_children,
        CategorySyncNameLookupError,
    )

    updated_count = 0
    already_current_count = 0
    failed_count = 0
    child_updated = 0
    child_paid_skipped = 0
    child_loop_skipped = 0
    child_error_rows = 0
    results: List[Dict[str, Any]] = []

    for tid in ordered_ids:
        tpl = await db.recurring_job_templates.find_one(
            {"id": tid, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1,
              "income_category_id": 1, "income_category_name": 1,
              "service_category_id": 1, "service_category_name": 1},
        )
        if not tpl:
            # Q2/A — out-of-tenant + typo + deleted all land in the
            # same failure bucket. Same honest-telemetry policy as
            # bulk-activate.
            failed_count += 1
            results.append({
                "id": tid, "status": "failed", "error": "not_found",
            })
            continue

        # Build the write set — idempotency guard: only include
        # fields whose resolved target differs from the current
        # value. Denormalized name stays in lockstep with the id.
        updates: Dict[str, Any] = {}
        for _field, _cat in resolved_by_field.items():
            _denorm = _field.replace("_id", "_name")
            if tpl.get(_field) != _cat["id"]:
                updates[_field] = _cat["id"]
            if tpl.get(_denorm) != _cat.get("name"):
                updates[_denorm] = _cat.get("name")

        if not updates:
            already_current_count += 1
            results.append({"id": tid, "status": "already_current"})
            continue

        updates["updated_at"] = now_iso()
        try:
            res = await db.recurring_job_templates.update_one(
                {"id": tid, "tenant_id": tenant["id"]},
                {"$set": updates},
            )
        except Exception as _upd_exc:                             # noqa: BLE001
            failed_count += 1
            results.append({
                "id": tid, "status": "failed",
                "error": f"update_failed: {_upd_exc}",
            })
            continue

        if res.matched_count == 0:
            # Race — template deleted between find_one + update_one.
            # Classify same as not_found for parity.
            failed_count += 1
            results.append({
                "id": tid, "status": "failed", "error": "not_found",
            })
            continue

        # Audit — reuse the existing writer (Q3/A · one row per
        # updated template, same event/diff shape as the
        # single-item PATCH). The writer's own no-op guard drops
        # the write if the diff is empty; here we've already
        # gated on ``updates`` non-empty so it will fire.
        await _write_recurring_category_audit(
            tenant_id=tenant["id"], tpl_id=tid, actor=user,
            before=tpl, updates=updates,
        )

        # P55 sync fan-out. Origin ``bulk_recurring_edit`` — grep-
        # verified NOT in ``_SKIP_TABLE`` (test guard in the P54
        # backend suite). Fail-open below: the template write
        # already landed, so a sync failure gets classified as a
        # per-row ``failed`` so the caller can see the partial-
        # apply state and ops can re-run a bulk backfill later.
        _sync_kwargs: Dict[str, Any] = {"origin": "bulk_recurring_edit"}
        if "income_category_id" in updates:
            _sync_kwargs["income_category_id"] = (
                updates["income_category_id"]
            )
        if "service_category_id" in updates:
            _sync_kwargs["service_category_id"] = (
                updates["service_category_id"]
            )
        try:
            _sync_result = await sync_recurring_template_to_children(
                tenant_id=tenant["id"],
                recurring_job_id=tid,
                actor_id=(user or {}).get("id"),
                **_sync_kwargs,
            )
            child_updated += _sync_result.updated_count
            child_paid_skipped += _sync_result.skipped_paid_count
            child_loop_skipped += _sync_result.skipped_loop_count
            child_error_rows += len(_sync_result.errors_by_id)
        except CategorySyncNameLookupError as _cs_exc:
            failed_count += 1
            results.append({
                "id": tid, "status": "failed",
                "error": ("category_deleted_after_source_write "
                            f"({_cs_exc.category_id})"),
            })
            continue
        except Exception as _cs_exc:                             # noqa: BLE001
            logger.warning(
                "[category_sync.bulk_recurring_edit.failed] "
                "template=%s error=%s", tid, _cs_exc,
            )
            failed_count += 1
            results.append({
                "id": tid, "status": "failed",
                "error": f"sync_failed: {_cs_exc}",
            })
            continue

        updated_count += 1
        results.append({"id": tid, "status": "updated"})

    return {
        "updated": updated_count,
        "already_current": already_current_count,
        "failed": failed_count,
        "sync_result_summary": {
            "child_invoices_updated": child_updated,
            "child_invoices_skipped_paid": child_paid_skipped,
            "child_invoices_skipped_loop": child_loop_skipped,
            "child_error_rows": child_error_rows,
        },
        "results": results,
    }


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

    Phase R1 · Feb-2026 — the ``hard=true`` branch delegates to
    ``_hard_delete_recurring_job`` so ``POST /recurring-jobs/bulk-
    delete`` can share the exact same removal + audit logic.  The
    per-row wire contract is preserved: this endpoint's response
    stays ``{id, hard_deleted: True, future_jobs_cancelled: N}``
    while the helper returns the newer, richer per-id status shape
    the bulk endpoint aggregates.
    """
    if hard:
        # Pre-Phase-R1 semantics: cancel visits STRICTLY AFTER today
        # (``scheduled_date > today``).  The helper's cutoff is a
        # ``>=`` comparator, so pass ``tomorrow`` to preserve
        # backwards-compat.
        tomorrow_iso = (date.today() + timedelta(days=1)).isoformat()
        result = await _hard_delete_recurring_job(
            tpl_id=tpl_id, actor=user, tenant_id=tenant["id"],
            today_anchor=tomorrow_iso,
        )
        if result["status"] == "not_found":
            raise HTTPException(404, "template not found")
        if result["status"] == "forbidden":  # pragma: no cover
            raise HTTPException(403, "template not owned by tenant")
        return {
            "id": tpl_id,
            "hard_deleted": True,
            "future_jobs_cancelled": result["future_visits_deleted"],
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


# Feb-2026 · P1 Auto-Activate + Instant Generation — 2-week horizon
# for inline visit creation. The nightly generator's existing longer
# horizon is unchanged; this constant applies ONLY to the inline
# hooks in create / patch / bulk-activate.
INSTANT_GENERATION_HORIZON_DAYS = 14


async def _instant_generate_for_template(
    tpl: Dict[str, Any], *, horizon_days: int = INSTANT_GENERATION_HORIZON_DAYS,
) -> Dict[str, Any]:
    """Fire ``_generate_from_template`` with a 14-day horizon starting
    from today. Instant generation covers 2 weeks so techs see the
    near-term visits without waiting for the nightly generator.

    Uniform start-date guard: when ``start_date`` is missing or fails
    to parse as a valid ISO date, we skip generation with an INFO log
    and return a well-formed no-op result. Callers do NOT reject the
    create/patch/bulk-activate request just because generation was
    skipped — the template can still be persisted; the user just
    won't see immediate visits until they supply a ``start_date``.

    Returns ``{inserted, skipped, dates, skipped_no_start_date}``.
    """
    _start_raw = tpl.get("start_date")
    if not _start_raw or not _parse_date(_start_raw):
        logger.info(
            "[recurring_job.instant_generation_skipped] template=%s "
            "reason=missing_start_date",
            tpl.get("id"),
        )
        return {"inserted": 0, "skipped": 0, "dates": [],
                "skipped_no_start_date": True}
    through = date.today() + timedelta(days=horizon_days)
    result = await _generate_from_template(tpl, through)
    result["skipped_no_start_date"] = False
    return result


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
        # Feb-2026 · Recurring Jobs · end_date auto-stop. When the
        # walker has crossed the template's inclusive end_date, the
        # occurrence generator returns [] every night forever —
        # burning a template read per active recurring template per
        # nightly cron for no work. Transition the template to the
        # existing terminal state (mirrors ``POST /stop``: active
        # False, end_date already set, ``recurrence_never_ends``
        # cleared, ``stopped_at`` stamped) so subsequent cron runs
        # skip it via the ``is_active/active`` filter.
        _end = _parse_date(tpl.get("end_date"))
        if _end and anchor > _end and (
            tpl.get("active") is not False
            or tpl.get("is_active") is not False
        ):
            await db.recurring_job_templates.update_one(
                {"id": tpl["id"], "tenant_id": tenant_id},
                {"$set": {"active": False, "is_active": False,
                            "recurrence_never_ends": False,
                            "stopped_at": now_iso(),
                            "updated_at": now_iso()}},
            )
            logger.info(
                "[recurring_job.auto_stopped] template=%s tenant=%s "
                "end_date=%s anchor=%s",
                tpl["id"], tenant_id, _end.isoformat(),
                anchor.isoformat(),
            )
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
