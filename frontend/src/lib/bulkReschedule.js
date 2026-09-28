/**
 * BULK-RESCHEDULE · Feb-2026 — extracted handler.
 *
 * Pulled out of ``CalendarSchedule.jsx`` so vitest can drive it in
 * isolation without paying the render cost of the 3.4-kloc calendar
 * component.  Callers inject the ``api`` / ``mustConfirm`` / toast /
 * lifecycle hooks — the helper is deliberately dep-injected so the
 * test can stub each surface.
 *
 * Contract:
 *
 *   * ``ids`` must be non-empty AND ``date`` must be a ``YYYY-MM-DD``
 *     string.  Malformed inputs toast an error and return
 *     ``{ok: false, reason: "invalid_input"}`` without hitting the
 *     server.
 *   * Prompts via ``mustConfirm`` — cancellation returns
 *     ``{ok: false, reason: "user_cancelled"}``.  No API call.
 *   * On 2xx: builds the success toast (with skipped suffix when
 *     ``skipped.length > 0``), logs the ``skipped`` array to the
 *     browser console, clears selection, and invokes ``onReload``.
 *   * On error: translates the API's ``error_code`` (via
 *     ``ERROR_CODE_TO_TEXT``) to a readable toast; falls back to
 *     the server message when the code is unknown.
 */
import { api as defaultApi } from "@/api";
import { mustConfirm as defaultMustConfirm }
  from "@/components/ui/confirm-dialog";

const YYYY_MM_DD = /^\d{4}-\d{2}-\d{2}$/;

export const ERROR_CODE_TO_TEXT = {
  too_many_job_ids:
    "Cannot reschedule more than 100 jobs at once. Select fewer.",
  no_job_ids: "No jobs selected.",
  invalid_scheduled_date:
    "Pick a valid future or recent date "
    + "(YYYY-MM-DD, no more than 90 days in the past).",
};


export async function bulkReschedule({
  ids,
  date,
  toast,
  onClear,
  onReload,
  api = defaultApi,
  mustConfirm = defaultMustConfirm,
  console: consoleObj = (typeof console !== "undefined"
                          ? console : { info: () => {} }),
}) {
  if (!Array.isArray(ids) || ids.length === 0
      || !YYYY_MM_DD.test(String(date || ""))) {
    toast?.("Pick a target date (YYYY-MM-DD).", "err");
    return { ok: false, reason: "invalid_input" };
  }
  const confirmed = await mustConfirm({
    title: "Bulk Reschedule",
    description:
      `Reschedule ${ids.length} `
      + `job${ids.length === 1 ? "" : "s"} to ${date}?`,
    confirmText: "Reschedule",
    cancelText: "Cancel",
    confirmTestId: "grid-move-confirm-dialog-ok",
    cancelTestId: "grid-move-confirm-dialog-cancel",
  });
  if (!confirmed) {
    return { ok: false, reason: "user_cancelled" };
  }

  try {
    const res = await api.post("/jobs/bulk-reschedule", {
      job_ids: ids,
      scheduled_date: date,
    });
    const rescheduled = Number(res?.rescheduled_count || 0);
    const skipped = Array.isArray(res?.skipped) ? res.skipped : [];
    let msg = `Rescheduled ${rescheduled} `
      + `job${rescheduled === 1 ? "" : "s"} to ${date}`;
    if (skipped.length > 0) {
      msg += ` (${skipped.length} skipped)`;
      consoleObj.info("[bulk-reschedule] skipped:", skipped);
    }
    toast?.(msg, skipped.length && !rescheduled ? "err" : "info");
    onClear?.();
    await onReload?.();
    return { ok: true, rescheduled, skipped };
  } catch (e) {
    const errCode =
      e?.data?.detail?.error_code
      || e?.body?.detail?.error_code
      || null;
    const errMsg =
      e?.data?.detail?.message
      || e?.body?.detail?.message
      || e?.message
      || "Bulk reschedule failed.";
    const readable = ERROR_CODE_TO_TEXT[errCode] || errMsg;
    toast?.(readable, "err");
    return { ok: false, reason: errCode || "error", message: readable };
  }
}
