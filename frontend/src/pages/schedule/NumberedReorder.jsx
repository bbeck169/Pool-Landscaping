/**
 * Feb-2026 · Numbered-order schedule reorder.
 *
 * Replaces the prior drag-and-drop route reorder with a simple
 * numeric-input model.  The design decision (confirmed by the user)
 * is that a tech's day is manually numbered using positive integers.
 * Sprint 3d · Feb-2026 update: numbers do NOT have to be unique
 * (the backend's insert-and-shift primitive treats a colliding
 * number as "insert here, shift everyone else"). Numbers still
 * must be positive integers in ``[1, MAX_ORDER_VALUE]``, no blanks.
 * The persistence contract is unchanged — we still POST
 * ``/jobs/reorder`` with the ordered ``job_ids``.  The client sorts
 * the day's jobs by the user's typed numbers in ascending order and
 * sends the resulting ids; the backend writes ``route_index`` 0..N-1
 * from that list, so the numbers themselves are UX-only.
 *
 * Two entry points ship here:
 *
 *   • ``useNumberedOrder(jobs, opts)`` — hook that backs both the
 *     inline per-card inputs and the bulk modal.  Owns the draft
 *     map keyed by job id, exposes an error-key set, and a
 *     ``buildOrderedIds`` helper that sorts by draft number.
 *
 *   • ``<BulkReorderModal jobs onClose onSaved />`` — the bulk
 *     "Reorder…" surface with an explicit Save button.  Save is
 *     disabled while any validation error exists.  On success the
 *     modal calls ``onSaved`` (schedule refresh) and closes itself.
 *
 * A ``<NumberOrderInput job={j} controller={c} />`` primitive is
 * exported for CalendarSchedule/TodaySchedule to drop into their
 * job cards.  On blur the primitive triggers ``controller.blurSave``
 * which auto-saves when — and only when — the whole day's draft is
 * valid.  Invalid drafts get a red border + a compact banner.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/api";
import { colors } from "@/theme";
// Feb-2026 · Phase C — Drag-and-drop replaces the numeric-input
// bulk modal. Re-exported via `BulkReorderModal` below so the two
// existing call sites (CalendarSchedule + TodaySchedule) pick it
// up without changing their import lines.
import { ReorderRouteModal as _ReorderRouteModal } from "@/pages/schedule/ReorderRouteModal";


/**
 * Maximum accepted numeric label.  Bumped from ``N = count of the
 * day's non-terminal jobs`` (the old contiguous rule) to a flat 50
 * so techs on an 11-job day can still type ``1, 5, 12`` without
 * hitting a validation cap.  50 aligns with the offline-cache
 * scope decision (a tech's week tops out around 50 jobs), so we
 * won't need to bump this again during Phase 1.
 */
export const MAX_ORDER_VALUE = 50;

// ── Phase P10 · Feb-2026 — canonical lane-error copy ──
// Kept as a module-scope constant so the vitest suite can assert
// on the exact string surfaced by <ReorderErrorBanner /> without
// duplicating the sentence in the test file.
export const REORDER_LANE_ERROR_TEXT =
  "Assign a technician or crew before reordering.";
export const REORDER_MIXED_LANE_ERROR_TEXT =
  "Reorder within a single technician or crew.";


/** Return the initial draft number map keyed by job id.
 *
 *  * ``initialOrder`` (Feb-2026 · Optimize Route) — when a list of
 *    job IDs is passed, the drafts are seeded 1..N in THAT order,
 *    ignoring the row's ``route_index``. Used by the Optimize Route
 *    button to pre-fill the modal with the recommended order.
 *  * Otherwise the drafts fall back to ``route_index + 1`` (1-based
 *    UX). Jobs missing an index get a positional guess by list
 *    position so every input renders a non-empty placeholder.
 */
function _initialDrafts(jobs, initialOrder = null) {
  const m = {};
  if (Array.isArray(initialOrder) && initialOrder.length) {
    // Rank each job by its position in the optimized list. Jobs
    // NOT in the list get an index after the tail so they still
    // render (should be rare — caller passes the full day's list).
    const rank = new Map();
    initialOrder.forEach((id, idx) => rank.set(id, idx + 1));
    const tail = initialOrder.length + 1;
    jobs.forEach((j) => {
      m[j.id] = String(rank.get(j.id) ?? tail);
    });
    return m;
  }
  const sorted = [...jobs].sort(
    (a, b) => (a.route_index ?? 9999) - (b.route_index ?? 9999),
  );
  sorted.forEach((j, i) => {
    const cur = Number.isFinite(j?.route_index) ? j.route_index + 1 : i + 1;
    m[j.id] = String(cur);
  });
  return m;
}


/** Validate the whole draft map.  Returns
 *   { valid, errorIds:Set<string>, message:string|null }
 *
 *  Sprint 3d · Feb-2026 — insert-and-shift semantics. Duplicates
 *  are NO LONGER an error: the backend's insert-and-shift
 *  primitive treats a colliding number as an "insert here, shift
 *  everyone else". Numbers still must be positive integers in
 *  ``[1, MAX_ORDER_VALUE]`` and non-blank. Gaps remain permitted
 *  for the bulk edit surface (the client sorts by drafts before
 *  persisting; per-input inline edits go through the new
 *  ``/jobs/reorder-day-route`` endpoint which contiguously
 *  renumbers server-side).
 */
function _validate(drafts, jobs) {
  const errorIds = new Set();
  const N = jobs.length;
  if (!N) return { valid: true, errorIds, message: null };

  let hasBlank = false;
  let hasNonInt = false;
  let hasOutOfRange = false;

  for (const j of jobs) {
    const raw = (drafts[j.id] ?? "").trim();
    if (!raw) { errorIds.add(j.id); hasBlank = true; continue; }
    const n = Number(raw);
    if (!Number.isInteger(n) || String(n) !== raw.replace(/^0+(?=\d)/, "")) {
      errorIds.add(j.id); hasNonInt = true; continue;
    }
    if (n < 1 || n > MAX_ORDER_VALUE) {
      errorIds.add(j.id); hasOutOfRange = true; continue;
    }
  }

  const valid = errorIds.size === 0;

  let message = null;
  if (!valid) {
    if (hasBlank) {
      message = `Every job needs a number.`;
    } else if (hasNonInt) {
      message = `Only whole numbers are allowed.`;
    } else if (hasOutOfRange) {
      message = `Numbers must be positive integers (1–${MAX_ORDER_VALUE}).`;
    } else {
      // Defence-in-depth — should be unreachable.
      message = `Job numbers are invalid.`;
    }
  }
  return { valid, errorIds, message };
}


export function useNumberedOrder(jobs, opts = {}) {
  const { onSaved, onError, techUserId, date, autoSave = true,
             initialOrder = null } = opts;

  const [drafts, setDrafts] = useState(() => _initialDrafts(jobs, initialOrder));
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState(null); // {kind, text}
  // ── Phase P10 · Feb-2026 — dedicated lane-scope banner ──
  // Distinct from the generic ``banner`` state so a stale "Route
  // saved" toast doesn't hide the more actionable "Assign a
  // technician or crew before reordering" call-to-action.
  // ``null`` = hidden; ``{text, code}`` renders <ReorderErrorBanner/>.
  const [laneBanner, setLaneBanner] = useState(null);

  // ── Phase P25 · Feb-2026 — actively-typing draft protection.
  // Pre-P25 the sync effect below unconditionally re-hydrated every
  // row from ``initialOrder`` / ``job.route_index`` when the server
  // pushed fresh values (reorder response, poll, WebSocket). That
  // clobbered the user's in-flight edit — they'd type ``7`` into a
  // row, the parent's optimistic update would re-fire the memo, and
  // the input would snap back to the server's stale ``3``.
  //
  // Fix: track the set of job ids whose input is currently focused
  // (or blurred within a 300ms grace window — covers the IME race
  // where a Chinese/Japanese IME candidate popup steals blur before
  // the composition commits). Rows in ``typingIds`` keep their
  // local draft; all other rows re-hydrate from the fresh server
  // data. React state (not a ref) so the effect below actually
  // re-runs when the typing set changes and a just-blurred row can
  // catch up to the latest server value once its 300ms grace
  // window elapses.
  const TYPING_GRACE_MS = 300;
  const [typingIds, setTypingIds] = useState(() => new Set());
  const blurTimersRef = React.useRef({});   // {jobId: setTimeout handle}
  const notifyFocus = useCallback((jobId) => {
    // Cancel any pending blur-eviction so the row stays in the set.
    const pending = blurTimersRef.current[jobId];
    if (pending) {
      clearTimeout(pending);
      delete blurTimersRef.current[jobId];
    }
    setTypingIds((prev) => {
      if (prev.has(jobId)) return prev;
      const next = new Set(prev);
      next.add(jobId);
      return next;
    });
  }, []);
  const notifyBlur = useCallback((jobId) => {
    // Debounce eviction — an input that lost focus more than
    // ~300ms ago drops OUT of the typing set (per spec) so the
    // next server push can update it. Guards against IME
    // recomposition races where blur → focus fires within a few ms.
    const existing = blurTimersRef.current[jobId];
    if (existing) clearTimeout(existing);
    blurTimersRef.current[jobId] = setTimeout(() => {
      delete blurTimersRef.current[jobId];
      setTypingIds((prev) => {
        if (!prev.has(jobId)) return prev;
        const next = new Set(prev);
        next.delete(jobId);
        return next;
      });
    }, TYPING_GRACE_MS);
  }, []);
  // Cleanup on unmount so a stale setTimeout can't stamp state on
  // an unmounted component.
  useEffect(() => () => {
    for (const h of Object.values(blurTimersRef.current)) {
      clearTimeout(h);
    }
    blurTimersRef.current = {};
  }, []);

  // Keep the draft map in sync when the day's jobs change (e.g., a
  // new job gets scheduled) OR when the server pushes fresh
  // ``route_index`` values (reorder response, poll refresh, WS
  // push). P25 · Feb-2026 — the merge rule changed from
  //   "keep every prior draft that still has a job row"
  // (pre-P25 — clobbered fresh server values with stale locals)
  // to
  //   "keep prior drafts ONLY for rows whose input is currently
  //    focused (in ``typingIds``); replace all other rows with the
  //    fresh server value".
  // This preserves the mid-edit gesture without letting stale
  // locals overwrite a reorder that the server just confirmed.
  useEffect(() => {
    setDrafts((prev) => {
      const fresh = _initialDrafts(jobs, initialOrder);
      const merged = { ...fresh };
      for (const id of Object.keys(prev)) {
        if (id in fresh && typingIds.has(id)) {
          merged[id] = prev[id];
        }
      }
      return merged;
    });
    // Note: intentionally depend on jobs + initialOrder identity —
    // when the optimizer produces a new order, the caller passes a
    // fresh array so the map resets to the new 1..N sequence.
    // ``typingIds`` is intentionally NOT in the dep array — the
    // effect fires only when the SERVER data (jobs / initialOrder)
    // changes; a focus/blur alone must not re-merge (otherwise
    // typing into a row and blurring would re-hydrate mid-keystroke
    // if the parent hadn't refetched yet).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs, initialOrder]);

  const validation = useMemo(() => _validate(drafts, jobs), [drafts, jobs]);

  const setInput = useCallback((jobId, value) => {
    // Only permit digits (or the empty string) — silent guard.
    if (value !== "" && !/^\d+$/.test(value)) return;
    setDrafts((cur) => ({ ...cur, [jobId]: value }));
  }, []);

  const buildOrderedIds = useCallback(() => {
    if (!validation.valid) return null;
    return [...jobs]
      .sort((a, b) => Number(drafts[a.id]) - Number(drafts[b.id]))
      .map((j) => j.id);
  }, [jobs, drafts, validation]);

  const save = useCallback(async () => {
    if (!validation.valid) {
      setBanner({ kind: "err", text: validation.message });
      return { ok: false, reason: "invalid" };
    }
    const orderedIds = buildOrderedIds();
    if (!orderedIds || orderedIds.length === 0) {
      return { ok: false, reason: "empty" };
    }
    setSaving(true);
    try {
      const body = { ordered_job_ids: orderedIds };
      if (techUserId) body.tech_user_id = techUserId;
      if (date) body.date = date;
      const r = await api.post("/jobs/reorder", body);
      setBanner({
        kind: "info",
        text: `Route saved · ${r?.updated ?? orderedIds.length}/${r?.expected ?? orderedIds.length} jobs.`,
      });
      // Phase P10 · Feb-2026 — clear the lane banner on success.
      setLaneBanner(null);
      onSaved?.(r);
      return { ok: true, response: r };
    } catch (e) {
      // Phase P10 · Feb-2026 — the widened backend now returns
      // 409 with a structured detail for lane-scope failures.
      // Surface those via the dedicated lane banner (actionable)
      // rather than the generic red toast (usually dismissed).
      // ``api.js`` attaches the parsed body under ``err.data``;
      // legacy call sites read ``err.body``; ``err.message`` is
      // set to ``detail.code`` when the FastAPI detail is a
      // bare-code object. Check all three shapes so the branch
      // fires regardless of which wrapper produced the error.
      const _code =
        e?.data?.detail?.code
        || e?.body?.detail?.code
        || e?.detail?.code
        || (typeof e?.message === "string" ? e.message : null);
      if (_code === "reorder_lane_mismatch"
          || _code === "reorder_unassigned_job") {
        setLaneBanner({ code: _code, text: REORDER_LANE_ERROR_TEXT });
        setBanner(null);
        onError?.(e);
        return { ok: false, reason: "api", error: e };
      }
      const msg = e?.message || "Reorder failed.";
      setBanner({ kind: "err", text: msg });
      onError?.(e);
      return { ok: false, reason: "api", error: e };
    } finally {
      setSaving(false);
    }
  }, [validation, buildOrderedIds, techUserId, date, onSaved, onError]);

  /** Sprint 3d · Feb-2026 — insert-and-shift for a single-job
   *  edit. Uses the new ``POST /api/jobs/reorder-day-route``
   *  endpoint which computes the target list server-side and
   *  contiguously renumbers.  Client-side duplicate validation is
   *  gone — the endpoint accepts any positive integer and clamps /
   *  shifts as needed.
   *
   *  Args:
   *    jobId       — the job being repositioned.
   *    newPosition — the 1-indexed slot the user typed.
   *  Returns { ok, response? } like ``save()``.
   */
  const insertShift = useCallback(async (jobId, newPosition) => {
    // Sprint 3d · Feb-2026 follow-up — resolve ``technician_id`` and
    // ``date`` from the *moved job itself*, not from the closure
    // hints.  On a multi-tech day view, the closure ``techUserId``
    // was seeded from the first reorderable job in the list, so
    // moving a job that belonged to a *different* tech shipped a
    // stale technician_id and the backend correctly rejected with
    // ``job_id not on this tech's day``.  The job row always carries
    // its own tech + date, so use them as the source of truth and
    // fall back to the hook-level hints only if the job data is
    // missing something.
    const job = jobs.find((j) => j.id === jobId);
    const resolvedTech = (job && (
      job.tech_user_id || job.assigned_to || job.technician_id
    )) || techUserId;
    const resolvedDate =
      (job?.scheduled_date ? String(job.scheduled_date).slice(0, 10) : "")
      || date;
    if (!resolvedTech || !resolvedDate) {
      // Phase P10 · Feb-2026 — was previously a silent drop
      // ("swallowed unresolvable-tech situations"). Surface via
      // the dedicated lane-scope banner so the operator sees the
      // reason and can assign a technician or crew from the
      // row's assign flow. Also clear any stale info banner so
      // the two banners don't stack awkwardly.
      setLaneBanner({
        code: "no_lane_resolvable",
        text: REORDER_LANE_ERROR_TEXT,
      });
      setBanner(null);
      return { ok: false, reason: "missing_tech_or_date" };
    }
    const posInt = parseInt(newPosition, 10);
    if (!Number.isFinite(posInt) || posInt < 1) {
      setBanner({ kind: "err", text: `Only whole numbers are allowed.` });
      return { ok: false, reason: "invalid_position" };
    }
    setSaving(true);
    try {
      const r = await api.post("/jobs/reorder-day-route", {
        date:          resolvedDate,
        technician_id: resolvedTech,
        job_id:        jobId,
        new_position:  posInt,
      });
      setBanner({
        kind: "info",
        text: r?.changed === false
          ? `No change — job already at position ${r?.new_position ?? posInt}.`
          : `Moved · ${r?.old_position ?? "?"} → ${r?.new_position ?? posInt}.`,
      });
      onSaved?.(r);
      return { ok: true, response: r };
    } catch (e) {
      // Phase P10 · Feb-2026 — parity with ``save()`` for the
      // single-input insert-shift path. Check every error shape
      // the api wrapper might expose the code under.
      const _code =
        e?.data?.detail?.code
        || e?.body?.detail?.code
        || e?.detail?.code
        || (typeof e?.message === "string" ? e.message : null);
      if (_code === "reorder_lane_mismatch"
          || _code === "reorder_unassigned_job") {
        setLaneBanner({ code: _code, text: REORDER_LANE_ERROR_TEXT });
        setBanner(null);
        onError?.(e);
        return { ok: false, reason: "api", error: e };
      }
      const msg = e?.body?.detail || e?.message || "Reorder failed.";
      setBanner({ kind: "err", text: String(msg) });
      onError?.(e);
      return { ok: false, reason: "api", error: e };
    } finally {
      setSaving(false);
    }
  }, [jobs, techUserId, date, onSaved, onError]);

  // Auto-save on blur. Sprint 3d · Feb-2026 — if the touched job's
  // typed value differs from its current (server) position, fire
  // the single-job insert-shift endpoint.  If no touched job or
  // the typed value matches server position, no-op.  Bulk saves
  // now flow through ``ReorderRouteModal`` (drag-and-drop), which
  // uses the full-list ``/jobs/reorder`` endpoint directly.
  //
  // Returns the ``insertShift`` result object (``{ok, response? |
  // reason, error?}``) so callers can drive optimistic rollback.
  const blurSave = useCallback(async (touchedJobId = null) => {
    if (!autoSave) return { ok: false, reason: "autosave_disabled" };
    // Legacy fall-back: no touched job id → whole-day validate +
    // full-list save (kept for the retired BulkReorderModal path).
    if (!touchedJobId) {
      if (!validation.valid) return { ok: false, reason: "invalid" };
      return await save();
    }
    // Single-input path — insert-and-shift.
    const raw = (drafts[touchedJobId] ?? "").trim();
    if (!raw) return { ok: false, reason: "blank" };
    const n = Number(raw);
    if (!Number.isInteger(n) || n < 1) {
      return { ok: false, reason: "invalid_position" };
    }
    const j = jobs.find((row) => row.id === touchedJobId);
    if (!j) return { ok: false, reason: "job_not_found" };
    const currentPosition =
      Number.isFinite(j?.route_index) ? j.route_index + 1 : null;
    if (currentPosition !== null && n === currentPosition) {
      return { ok: true, response: { changed: false, new_position: n } };
    }
    return await insertShift(touchedJobId, n);
  }, [autoSave, validation, save, drafts, jobs, insertShift]);

  const reset = useCallback(() => setDrafts(_initialDrafts(jobs)), [jobs]);

  return {
    drafts, setInput, validation, saving, banner, setBanner,
    // Phase P10 · Feb-2026 — dedicated lane-scope banner + a
    // setter so consumers can programmatically raise it (e.g.,
    // CalendarSchedule when the day spans multiple lanes and the
    // user tries to open the Reorder modal anyway).
    laneBanner, setLaneBanner,
    save, blurSave, reset, buildOrderedIds, insertShift,
    // Phase P25 · Feb-2026 — actively-typing draft protection.
    // ``notifyFocus`` / ``notifyBlur`` are wired into the
    // ``NumberOrderInput`` primitive so its focus/blur transitions
    // toggle the ``typingIds`` set that gates the sync-effect
    // merge above. ``typingIds`` is exposed too so tests (and
    // consumer components that build their own number inputs)
    // can assert / participate.
    notifyFocus, notifyBlur, typingIds,
  };
}


// ── Phase P10 · Feb-2026 — Lane-scope error banner. ────────────
// Renders when the hook's ``laneBanner`` is non-null OR the
// consumer forces a message via a ``value`` prop (used by
// CalendarSchedule for the "day spans multiple lanes" gesture-
// layer notice). Kept separate from the pre-existing generic
// ``ReorderBanner`` so the sticky call-to-action doesn't get
// overwritten by a stale success toast.
export function ReorderErrorBanner({ controller, value = null, onDismiss }) {
  const raised = value || controller?.laneBanner || null;
  if (!raised) return null;
  const handleDismiss = () => {
    controller?.setLaneBanner?.(null);
    onDismiss?.();
  };
  return (
    <div
      className="rounded-lg px-3 py-2 mb-3 text-xs font-semibold flex items-center justify-between gap-2"
      style={{
        background: "#FEF3C7",
        color:      "#92400E",
        border:     "1px solid #FDE68A",
      }}
      data-testid="reorder-error-banner"
      role="alert"
    >
      <span>{raised.text || REORDER_LANE_ERROR_TEXT}</span>
      <button
        type="button"
        onClick={handleDismiss}
        aria-label="Dismiss reorder error"
        className="rounded p-0.5 hover:bg-black/5"
        style={{ color: "#92400E", lineHeight: 1 }}
        data-testid="reorder-error-banner-dismiss"
      >
        ×
      </button>
    </div>
  );
}


export function NumberOrderInput({ job, controller, disabled, testId, autoFocus }) {
  const isErr = controller.validation.errorIds.has(job.id);
  // Sprint 3d · Feb-2026 — track the original value on focus so we
  // can revert on API failure (optimistic rollback).
  const [preEditValue, setPreEditValue] = React.useState(null);
  return (
    <input
      type="number"
      inputMode="numeric"
      min={1}
      max={MAX_ORDER_VALUE}
      step={1}
      value={controller.drafts[job.id] ?? ""}
      placeholder="—"
      autoFocus={autoFocus}
      onFocus={() => {
        setPreEditValue(controller.drafts[job.id] ?? "");
        // Phase P25 · Feb-2026 — mark this row as actively typing
        // so the sync effect in ``useNumberedOrder`` preserves the
        // in-flight draft when the server pushes fresh values.
        controller.notifyFocus?.(job.id);
      }}
      onChange={(e) => controller.setInput(job.id, e.target.value)}
      onBlur={async () => {
        // Sprint 3d · Feb-2026 — pass the touched job id so the
        // hook fires the insert-shift endpoint for this row only.
        // On API failure the input is reverted to the pre-focus
        // value (optimistic rollback).
        //
        // Phase P25 · Feb-2026 — schedule the row's exit from the
        // ``typingIds`` set (300ms grace). Called BEFORE the save
        // so the IME edge-case (blur → immediate refocus during
        // composition) still keeps the row protected.
        controller.notifyBlur?.(job.id);
        const cur = (controller.drafts[job.id] ?? "").trim();
        if (cur === preEditValue) return;
        const r = await controller.blurSave(job.id);
        if (r && r.ok === false && preEditValue !== null) {
          controller.setInput(job.id, preEditValue);
        }
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.currentTarget.blur();
        }
      }}
      onClick={(e) => e.stopPropagation()}
      disabled={disabled || controller.saving}
      data-testid={testId || `route-order-input-${job.id}`}
      className="reorder-num-input"
      aria-label={`Order number for ${job.customer_name || job.title || "job"}`}
      aria-invalid={isErr ? "true" : "false"}
      style={{
        width: 44,
        height: 32,
        padding: "0 6px",
        borderRadius: 8,
        border: `1.5px solid ${isErr ? "#DC2626" : colors.border}`,
        background: isErr ? "#FEF2F2" : colors.surface,
        color: isErr ? "#991B1B" : colors.onSurface,
        fontWeight: 700,
        fontSize: 13,
        textAlign: "center",
        outline: "none",
      }}
    />
  );
}


export function ReorderBanner({ controller }) {
  const { banner, validation } = controller;
  // Live-error takes precedence over stale success/error banner text.
  const text = !validation.valid ? validation.message : banner?.text;
  const kind = !validation.valid ? "err" : banner?.kind || "info";
  if (!text) return null;
  const isErr = kind === "err";
  return (
    <div
      className="rounded-lg px-3 py-2 mb-3 text-xs font-semibold flex items-center gap-2"
      style={{
        background: isErr ? "#FEE2E2" : "#DCFCE7",
        color:      isErr ? "#991B1B" : "#166534",
        border:     `1px solid ${isErr ? "#FCA5A5" : "#86EFAC"}`,
      }}
      data-testid={isErr ? "route-order-error-banner" : "route-order-info-banner"}
    >
      {text}
    </div>
  );
}


export function BulkReorderModal(props) {
  // Feb-2026 · Phase C — the historical "type a unique number" modal
  // is retired in favor of drag-and-drop. Keep the export name so
  // both CalendarSchedule + TodaySchedule pick up the new UX without
  // touching their import lists. See ReorderRouteModal.jsx.
  return <_ReorderRouteModal {...props} />;
}

