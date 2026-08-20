/**
 * Feb-2026 · Numbered-order schedule reorder.
 *
 * Replaces the prior drag-and-drop route reorder with a simple
 * numeric-input model.  The design decision (confirmed by the user)
 * is that a tech's day is manually numbered 1..N where N = count of
 * non-terminal jobs on that tech's day.  Numbers must be unique
 * positive integers, no blanks, no gaps.  The persistence contract
 * is unchanged — we still POST ``/jobs/reorder`` with the ordered
 * ``job_ids`` (the backend now enforces the set-completeness rule).
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
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { X, Save as SaveIcon } from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";


/** Return the initial draft number map keyed by job id.  Each entry
 *  is a string (inputs are text boxes) — the current ``route_index``
 *  is offset by +1 for 1-based UX.  Jobs with no assigned index get
 *  an empty string so the input renders as a placeholder ``—``. */
function _initialDrafts(jobs) {
  const m = {};
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
 *   { valid, errorIds:Set<string>, message:string|null } */
function _validate(drafts, jobs) {
  const errorIds = new Set();
  const N = jobs.length;
  if (!N) return { valid: true, errorIds, message: null };

  const seen = new Map(); // value → first job id
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
    if (n < 1 || n > N) {
      errorIds.add(j.id); hasOutOfRange = true; continue;
    }
    if (seen.has(n)) {
      errorIds.add(j.id);
      errorIds.add(seen.get(n));
    } else {
      seen.set(n, j.id);
    }
  }

  const hasDup = errorIds.size > seen.size && !hasBlank && !hasNonInt && !hasOutOfRange;
  const valid = errorIds.size === 0;

  let message = null;
  if (!valid) {
    if (hasBlank) {
      message = `All jobs must have a number 1–${N}.`;
    } else if (hasNonInt) {
      message = `Only whole numbers are allowed.`;
    } else if (hasOutOfRange) {
      message = `Numbers must be between 1 and ${N}.`;
    } else {
      message = `Job orders must be unique 1–${N}.`;
    }
    // Suppress-flag left in place for grep-friendliness in code review.
    void hasDup;
  }
  return { valid, errorIds, message };
}


export function useNumberedOrder(jobs, opts = {}) {
  const { onSaved, onError, techUserId, date, autoSave = true } = opts;

  const [drafts, setDrafts] = useState(() => _initialDrafts(jobs));
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState(null); // {kind, text}

  // Keep the draft map in sync when the day's jobs change (e.g., a
  // new job gets scheduled).  Preserve any edits the user has made
  // for existing job ids.
  useEffect(() => {
    setDrafts((prev) => {
      const fresh = _initialDrafts(jobs);
      const merged = { ...fresh };
      for (const id of Object.keys(prev)) {
        if (id in fresh) merged[id] = prev[id];
      }
      return merged;
    });
  }, [jobs]);

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
      onSaved?.(r);
      return { ok: true, response: r };
    } catch (e) {
      const msg = e?.message || "Reorder failed.";
      setBanner({ kind: "err", text: msg });
      onError?.(e);
      return { ok: false, reason: "api", error: e };
    } finally {
      setSaving(false);
    }
  }, [validation, buildOrderedIds, techUserId, date, onSaved, onError]);

  // Only auto-save on blur when the whole day is valid — otherwise
  // the user's still mid-edit and we shouldn't spam the API.
  const blurSave = useCallback(async () => {
    if (!autoSave) return;
    if (!validation.valid) return;
    await save();
  }, [autoSave, validation, save]);

  const reset = useCallback(() => setDrafts(_initialDrafts(jobs)), [jobs]);

  return {
    drafts, setInput, validation, saving, banner, setBanner,
    save, blurSave, reset, buildOrderedIds,
  };
}


export function NumberOrderInput({ job, controller, disabled, testId, autoFocus }) {
  const isErr = controller.validation.errorIds.has(job.id);
  return (
    <input
      type="number"
      inputMode="numeric"
      min={1}
      max={Object.keys(controller.drafts).length || 1}
      step={1}
      value={controller.drafts[job.id] ?? ""}
      placeholder="—"
      autoFocus={autoFocus}
      onChange={(e) => controller.setInput(job.id, e.target.value)}
      onBlur={() => controller.blurSave()}
      onClick={(e) => e.stopPropagation()}
      disabled={disabled || controller.saving}
      data-testid={testId || `route-order-input-${job.id}`}
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


export function BulkReorderModal({ jobs, techUserId, date, onClose, onSaved }) {
  const controller = useNumberedOrder(jobs, {
    autoSave: false, techUserId, date,
    onSaved: (r) => { onSaved?.(r); onClose?.(); },
  });
  const overlayRef = useRef(null);

  return (
    <div
      ref={overlayRef}
      onClick={(e) => { if (e.target === overlayRef.current) onClose?.(); }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      data-testid="bulk-reorder-backdrop"
    >
      <div
        className="w-full max-w-xl rounded-2xl overflow-hidden shadow-2xl flex flex-col"
        style={{ background: colors.surface, maxHeight: "80vh" }}
        data-testid="bulk-reorder-modal"
      >
        <header
          className="px-5 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div>
            <div className="text-base font-bold" style={{ color: colors.onSurface }}>
              Reorder route
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              Number every job 1–{jobs.length}. Duplicates and blanks block Save.
            </div>
          </div>
          <button onClick={onClose} data-testid="bulk-reorder-close" style={{ color: colors.muted }}>
            <X size={18} />
          </button>
        </header>

        <div className="px-5 py-3" style={{ borderBottom: `1px solid ${colors.border}` }}>
          <ReorderBanner controller={controller} />
        </div>

        <div className="px-5 py-3 overflow-y-auto flex flex-col gap-2" style={{ flex: 1 }}>
          {jobs.length === 0 ? (
            <div className="text-sm text-center py-6" style={{ color: colors.muted }}>
              No jobs on this day.
            </div>
          ) : jobs.map((j) => (
            <div
              key={j.id}
              className="flex items-center gap-3 rounded-xl px-3 py-2"
              style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
              data-testid={`bulk-reorder-row-${j.id}`}
            >
              <NumberOrderInput
                job={j}
                controller={controller}
                testId={`bulk-reorder-input-${j.id}`}
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold truncate" style={{ color: colors.onSurface }}>
                  {j.customer_name || j.title || "Job"}
                </div>
                <div className="text-xs truncate" style={{ color: colors.muted }}>
                  {(j.scheduled_time || j.scheduled_at || "").slice(11, 16) || ""}
                  {j.address ? ` · ${j.address}` : ""}
                </div>
              </div>
            </div>
          ))}
        </div>

        <footer
          className="px-5 py-3 flex justify-end gap-2"
          style={{
            borderTop: `1px solid ${colors.border}`,
            background: colors.surfaceSecondary,
          }}
        >
          <button
            onClick={onClose}
            className="px-3 py-2 rounded-lg text-sm font-semibold"
            style={{ color: colors.muted, background: "transparent" }}
            data-testid="bulk-reorder-cancel"
          >
            Cancel
          </button>
          <button
            onClick={() => controller.save()}
            disabled={!controller.validation.valid || controller.saving || !jobs.length}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-bold"
            style={{
              background: "#059669",
              color: "#fff",
              opacity:
                !controller.validation.valid || controller.saving || !jobs.length ? 0.45 : 1,
            }}
            data-testid="bulk-reorder-save"
          >
            <SaveIcon size={14} />
            {controller.saving ? "Saving…" : "Save order"}
          </button>
        </footer>
      </div>
    </div>
  );
}
