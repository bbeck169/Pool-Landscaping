/**
 * BULK-RESCHEDULE · Feb-2026 — vitest coverage for the extracted
 * ``bulkReschedule`` helper (source of truth for the Schedule page's
 * "Bulk Reschedule" pill).
 *
 * Locks the FE contract:
 *
 *   * Confirmation dialog opens with the exact
 *     ``Reschedule N jobs to <date>?`` copy.
 *   * Confirm calls ``POST /jobs/bulk-reschedule`` with the
 *     ``{job_ids, scheduled_date}`` body.
 *   * Success toast text mirrors the server's ``rescheduled_count``
 *     with a ``(M skipped)`` suffix ONLY when
 *     ``skipped.length > 0``.
 *   * Selection is cleared via ``onClear`` after success.
 *   * Reload helper is invoked after success.
 *   * ``too_many_job_ids`` error → readable-toast translation.
 *   * User cancel → no API call, no toast, no reload.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

import {
  bulkReschedule,
  ERROR_CODE_TO_TEXT,
} from "@/lib/bulkReschedule";


function _harness(overrides = {}) {
  return {
    ids: ["j1", "j2", "j3"],
    date: "2026-03-15",
    toast: vi.fn(),
    onClear: vi.fn(),
    onReload: vi.fn().mockResolvedValue(undefined),
    api: { post: vi.fn() },
    mustConfirm: vi.fn().mockResolvedValue(true),
    console: { info: vi.fn() },
    ...overrides,
  };
}


describe("BULK-RESCHEDULE · @/lib/bulkReschedule", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("confirms with the correct copy before firing the API call",
     async () => {
       const h = _harness({ ids: ["a", "b", "c"], date: "2026-03-15" });
       h.api.post.mockResolvedValue({
         rescheduled_count: 3, skipped: [], target_date: "2026-03-15",
       });
       await bulkReschedule(h);
       expect(h.mustConfirm).toHaveBeenCalledTimes(1);
       const opts = h.mustConfirm.mock.calls[0][0];
       expect(opts.title).toBe("Bulk Reschedule");
       expect(opts.description)
         .toBe("Reschedule 3 jobs to 2026-03-15?");
       expect(opts.confirmText).toBe("Reschedule");
       expect(opts.cancelText).toBe("Cancel");
     });

  it("uses singular 'job' when only one id is selected",
     async () => {
       const h = _harness({ ids: ["a"], date: "2026-03-15" });
       h.api.post.mockResolvedValue({
         rescheduled_count: 1, skipped: [], target_date: "2026-03-15",
       });
       await bulkReschedule(h);
       expect(h.mustConfirm.mock.calls[0][0].description)
         .toBe("Reschedule 1 job to 2026-03-15?");
     });

  it("POSTs /jobs/bulk-reschedule with the correct body", async () => {
    const h = _harness();
    h.api.post.mockResolvedValue({
      rescheduled_count: 3, skipped: [], target_date: "2026-03-15",
    });
    await bulkReschedule(h);
    expect(h.api.post).toHaveBeenCalledTimes(1);
    expect(h.api.post).toHaveBeenCalledWith(
      "/jobs/bulk-reschedule",
      { job_ids: ["j1", "j2", "j3"],
        scheduled_date: "2026-03-15" },
    );
  });

  it("success toast has NO '(M skipped)' suffix when skipped is empty",
     async () => {
       const h = _harness({ ids: ["a", "b"], date: "2026-03-15" });
       h.api.post.mockResolvedValue({
         rescheduled_count: 2, skipped: [], target_date: "2026-03-15",
       });
       await bulkReschedule(h);
       expect(h.toast).toHaveBeenCalledWith(
         "Rescheduled 2 jobs to 2026-03-15", "info",
       );
     });

  it("success toast INCLUDES '(M skipped)' when server skipped rows",
     async () => {
       const h = _harness({ ids: ["a", "b", "c", "d"],
                              date: "2026-03-15" });
       h.api.post.mockResolvedValue({
         rescheduled_count: 2,
         skipped: [{ job_id: "c", reason: "soft_deleted" },
                    { job_id: "d", reason: "locked" }],
         target_date: "2026-03-15",
       });
       await bulkReschedule(h);
       expect(h.toast).toHaveBeenCalledWith(
         "Rescheduled 2 jobs to 2026-03-15 (2 skipped)", "info",
       );
       // Skipped array logged for admin debugging.
       expect(h.console.info).toHaveBeenCalledWith(
         "[bulk-reschedule] skipped:",
         expect.arrayContaining([
           expect.objectContaining({ job_id: "c",
                                       reason: "soft_deleted" }),
         ]),
       );
     });

  it("toast is 'err' when EVERY job got skipped (all-fail path)",
     async () => {
       const h = _harness({ ids: ["a", "b"], date: "2026-03-15" });
       h.api.post.mockResolvedValue({
         rescheduled_count: 0,
         skipped: [{ job_id: "a", reason: "locked" },
                    { job_id: "b", reason: "locked" }],
         target_date: "2026-03-15",
       });
       await bulkReschedule(h);
       expect(h.toast).toHaveBeenCalledWith(
         "Rescheduled 0 jobs to 2026-03-15 (2 skipped)", "err",
       );
     });

  it("clears selection and reloads after success", async () => {
    const h = _harness();
    h.api.post.mockResolvedValue({
      rescheduled_count: 3, skipped: [], target_date: "2026-03-15",
    });
    await bulkReschedule(h);
    expect(h.onClear).toHaveBeenCalledTimes(1);
    expect(h.onReload).toHaveBeenCalledTimes(1);
  });

  it("returns a structured result on success", async () => {
    const h = _harness();
    h.api.post.mockResolvedValue({
      rescheduled_count: 3, skipped: [], target_date: "2026-03-15",
    });
    const res = await bulkReschedule(h);
    expect(res).toEqual({ ok: true, rescheduled: 3, skipped: [] });
  });

  // ─── Error handling ───────────────────────────────────────────

  it("too_many_job_ids surfaces a readable toast", async () => {
    const h = _harness();
    h.api.post.mockRejectedValue({
      data: { detail: { error_code: "too_many_job_ids",
                           limit: 100, received: 250,
                           message: "capped at 100" } },
    });
    const res = await bulkReschedule(h);
    expect(h.toast).toHaveBeenCalledWith(
      ERROR_CODE_TO_TEXT.too_many_job_ids, "err",
    );
    expect(res.ok).toBe(false);
    expect(res.reason).toBe("too_many_job_ids");
    // Reload NOT invoked on error.
    expect(h.onReload).not.toHaveBeenCalled();
    expect(h.onClear).not.toHaveBeenCalled();
  });

  it("no_job_ids error surfaces a readable toast", async () => {
    const h = _harness();
    h.api.post.mockRejectedValue({
      data: { detail: { error_code: "no_job_ids",
                           message: "job_ids is empty" } },
    });
    await bulkReschedule(h);
    expect(h.toast).toHaveBeenCalledWith(
      ERROR_CODE_TO_TEXT.no_job_ids, "err",
    );
  });

  it("invalid_scheduled_date error surfaces a readable toast",
     async () => {
       const h = _harness();
       h.api.post.mockRejectedValue({
         body: { detail: { error_code: "invalid_scheduled_date",
                               message: "past" } },
       });
       await bulkReschedule(h);
       expect(h.toast).toHaveBeenCalledWith(
         ERROR_CODE_TO_TEXT.invalid_scheduled_date, "err",
       );
     });

  it("unknown error_code falls back to server message",
     async () => {
       const h = _harness();
       h.api.post.mockRejectedValue({
         data: { detail: { error_code: "unknown_new_code",
                              message: "some new server error" } },
       });
       await bulkReschedule(h);
       expect(h.toast).toHaveBeenCalledWith(
         "some new server error", "err",
       );
     });

  it("no error_code at all falls back to generic message", async () => {
    const h = _harness();
    h.api.post.mockRejectedValue(new Error("network down"));
    await bulkReschedule(h);
    expect(h.toast).toHaveBeenCalledWith("network down", "err");
  });

  // ─── Input validation & lifecycle ────────────────────────────

  it("empty ids → invalid_input toast + no api call", async () => {
    const h = _harness({ ids: [] });
    const res = await bulkReschedule(h);
    expect(res).toEqual({ ok: false, reason: "invalid_input" });
    expect(h.mustConfirm).not.toHaveBeenCalled();
    expect(h.api.post).not.toHaveBeenCalled();
    expect(h.toast).toHaveBeenCalledWith(
      "Pick a target date (YYYY-MM-DD).", "err",
    );
  });

  it("malformed date → invalid_input toast + no api call",
     async () => {
       const h = _harness({ date: "yesterday" });
       const res = await bulkReschedule(h);
       expect(res.reason).toBe("invalid_input");
       expect(h.mustConfirm).not.toHaveBeenCalled();
       expect(h.api.post).not.toHaveBeenCalled();
     });

  it("user cancels the confirm → NO api call and NO toast",
     async () => {
       const h = _harness({
         mustConfirm: vi.fn().mockResolvedValue(false),
       });
       const res = await bulkReschedule(h);
       expect(res).toEqual({ ok: false, reason: "user_cancelled" });
       expect(h.api.post).not.toHaveBeenCalled();
       expect(h.toast).not.toHaveBeenCalled();
       expect(h.onClear).not.toHaveBeenCalled();
       expect(h.onReload).not.toHaveBeenCalled();
     });
});
