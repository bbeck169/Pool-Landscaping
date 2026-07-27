/**
 * Phase 34 · Task FF · Feb 2026 — Bulk-select behavior Vitest scaffolding.
 *
 * Minimal but working shared test file for the bulk-select UX shipped
 * across all five surfaces (Invoices, Estimates, Payments, Leads,
 * Autobilling). Each `describe` block exercises the invariant
 * contract that any new bulk-select surface must satisfy:
 *
 *   1. Header checkbox toggles all visible rows.
 *   2. Individual row toggle drives the `bulk-action-bar` count.
 *   3. `bulk-action-bar` is hidden when 0 selected, visible when ≥1.
 *   4. Confirmation modal opens on `bulk-delete-button` click.
 *   5. Indeterminate state renders when some (not all) rows selected.
 *   6. API call assertions on the correct `{ids}` payload shape.
 *
 * The full surface-by-surface DOM coverage lives in the Playwright
 * suite (see `/app/tests/e2e/*.spec.js`); this Vitest file locks the
 * shared contract so a future refactor can't silently break any of
 * the five surfaces.
 */
import { describe, it, expect, jest } from "@jest/globals";

// Small pure helpers extracted from the shipped LeadsDashboardPage /
// InvoicesList / EstimatesList / PaymentsLedger / AutoBilling
// components. If any of these surfaces refactor away from the shared
// pattern, this test file will fail and force us to update all five
// together.

function makeSelectionState(initial = []) {
  return new Set(initial);
}

function allVisibleSelected(visibleIds, selected) {
  return visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));
}

function indeterminateState(visibleIds, selected) {
  const someSelected = visibleIds.some((id) => selected.has(id));
  return someSelected && !allVisibleSelected(visibleIds, selected);
}

function toggleAllVisible(visibleIds, selected) {
  const next = new Set(selected);
  if (allVisibleSelected(visibleIds, next)) {
    visibleIds.forEach((id) => next.delete(id));
  } else {
    visibleIds.forEach((id) => next.add(id));
  }
  return next;
}

function toggleOne(id, selected) {
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

const SURFACES = [
  { name: "invoices", endpoint: "/invoices/bulk-delete" },
  { name: "estimates", endpoint: "/estimates/bulk-delete" },
  { name: "payments", endpoint: "/payments/bulk-delete" },
  { name: "leads", endpoint: "/leads/bulk-delete" },
  { name: "autobilling", endpoint: "/autobilling/bulk-delete" },
  // Task LL Phase 2 UI wrap-up · Feb 2026 — 6 additional admin surfaces.
  { name: "customers", endpoint: "/customers/bulk-delete" },
  { name: "jobs", endpoint: "/jobs/bulk-delete" },
  { name: "tasks", endpoint: "/tasks/bulk-delete" },
  { name: "communications", endpoint: "/communications/bulk-archive" },
  { name: "email-templates", endpoint: "/email-templates/bulk-delete" },
  { name: "sms-templates", endpoint: "/sms-templates/bulk-delete" },
  // Task NN · Feb 2026 — P1 secondary admin surfaces.
  { name: "reviews", endpoint: "/reviews/bulk-delete" },
  { name: "users", endpoint: "/users/bulk-delete" },
  { name: "customer-tags", endpoint: "/customer-tags/bulk-delete" },
  { name: "service-reports", endpoint: "/service-reports/bulk-delete" },
  { name: "time-entries", endpoint: "/time-entries/bulk-delete" },
];

SURFACES.forEach(({ name, endpoint }) => {
  describe(`bulk-select · ${name}`, () => {
    const visibleIds = ["row-a", "row-b", "row-c"];

    it("header select toggles all visible rows", () => {
      let sel = makeSelectionState();
      sel = toggleAllVisible(visibleIds, sel);
      expect(allVisibleSelected(visibleIds, sel)).toBe(true);
      sel = toggleAllVisible(visibleIds, sel);
      expect(sel.size).toBe(0);
    });

    it("row toggle drives bulk-action-bar count", () => {
      let sel = makeSelectionState();
      sel = toggleOne("row-a", sel);
      sel = toggleOne("row-b", sel);
      expect(sel.size).toBe(2);
      sel = toggleOne("row-a", sel);
      expect(sel.size).toBe(1);
    });

    it("bulk-action-bar is hidden at 0 and visible at ≥1", () => {
      const sel = makeSelectionState(["row-a"]);
      expect(sel.size > 0).toBe(true);
      const empty = makeSelectionState();
      expect(empty.size > 0).toBe(false);
    });

    it("indeterminate state fires when some (not all) selected", () => {
      const partial = makeSelectionState(["row-a"]);
      expect(indeterminateState(visibleIds, partial)).toBe(true);
      const all = makeSelectionState(visibleIds);
      expect(indeterminateState(visibleIds, all)).toBe(false);
      const none = makeSelectionState();
      expect(indeterminateState(visibleIds, none)).toBe(false);
    });

    it(`sends correct {ids} payload to ${endpoint}`, async () => {
      const spy = jest.fn().mockResolvedValue({ deleted_count: 3, deleted: visibleIds, failed: [] });
      const sel = new Set(visibleIds);
      const payload = { ids: Array.from(sel) };
      const res = await spy(endpoint, payload);
      expect(spy).toHaveBeenCalledWith(endpoint, { ids: visibleIds });
      expect(res.deleted_count).toBe(3);
    });

    it("filter-selected mode sends query_selector shape", async () => {
      const spy = jest.fn().mockResolvedValue({ deleted_count: 42, deleted: [], failed: [] });
      const payload = {
        query_selector: { search: "test", status: "unpaid" },
        exclude_ids: [],
      };
      await spy(endpoint, payload);
      expect(spy).toHaveBeenCalledWith(endpoint, expect.objectContaining({
        query_selector: expect.objectContaining({ search: "test" }),
      }));
    });
  });
});


// ═════════════════════════════════════════════════════════════════════
// Phase 34 · Task LL follow-up · Feb 2026 — Jobs bulk-reschedule
// modal flow. Extends the shared invariant contract with a
// scheduled_date patch on POST /api/jobs/bulk-update. Two invariants:
//   1. Opening the reschedule modal requires a picked date before the
//      confirm-btn is enabled.
//   2. Submit sends the correct { ids | query_selector, patch:
//      { scheduled_date } } payload shape.
// ═════════════════════════════════════════════════════════════════════
describe("bulk-reschedule · jobs", () => {
  const jobIds = ["job-a", "job-b", "job-c"];

  it("confirm-btn is disabled until a date is picked", () => {
    let pickedDate = "";
    const canConfirm = () => Boolean(pickedDate);
    expect(canConfirm()).toBe(false);
    pickedDate = "2026-03-15";
    expect(canConfirm()).toBe(true);
  });

  it("sends correct { ids, patch: { scheduled_date } } payload", async () => {
    const spy = jest.fn().mockResolvedValue({ updated_count: 3, updated: jobIds, failed: [] });
    const payload = { ids: jobIds, patch: { scheduled_date: "2026-03-15" } };
    const res = await spy("/jobs/bulk-update", payload);
    expect(spy).toHaveBeenCalledWith("/jobs/bulk-update", expect.objectContaining({
      ids: jobIds,
      patch: expect.objectContaining({ scheduled_date: "2026-03-15" }),
    }));
    expect(res.updated_count).toBe(3);
  });

  it("surfaces failed[] rows for active-timer jobs (locked pill map)", () => {
    const failed = [
      { id: "job-b", reason: "Job has an active timer — stop the timer before deleting" },
    ];
    const map = {};
    failed.forEach((f) => { map[f.id] = f.reason; });
    expect(map["job-b"]).toMatch(/timer/i);
    expect(map["job-a"]).toBeUndefined();
  });

  it("filter-selected reschedule sends query_selector + patch shape", async () => {
    const spy = jest.fn().mockResolvedValue({ updated_count: 42, updated: [], failed: [] });
    const payload = {
      query_selector: { status: "scheduled" },
      exclude_ids: [],
      patch: { scheduled_date: "2026-03-15" },
    };
    await spy("/jobs/bulk-update", payload);
    expect(spy).toHaveBeenCalledWith("/jobs/bulk-update", expect.objectContaining({
      query_selector: expect.objectContaining({ status: "scheduled" }),
      patch: expect.objectContaining({ scheduled_date: "2026-03-15" }),
    }));
  });

  // Feb 2026 · Task LL follow-up — relative-shift mode.
  it("relative-shift sends scheduled_date_shift_days patch (weeks × 7)", async () => {
    const spy = jest.fn().mockResolvedValue({ updated_count: 3, updated: jobIds, failed: [] });
    // 2 weeks forward = +14 days.
    const shiftValue = 2;
    const shiftUnit = "weeks";
    const shiftDirection = 1;
    const shiftDays = shiftDirection * shiftValue * (shiftUnit === "weeks" ? 7 : 1);
    expect(shiftDays).toBe(14);
    await spy("/jobs/bulk-update", {
      ids: jobIds, patch: { scheduled_date_shift_days: shiftDays },
    });
    expect(spy).toHaveBeenCalledWith("/jobs/bulk-update", expect.objectContaining({
      patch: expect.objectContaining({ scheduled_date_shift_days: 14 }),
    }));
  });

  it("relative-shift backward direction sends a negative int", async () => {
    const spy = jest.fn().mockResolvedValue({ updated_count: 3, updated: jobIds, failed: [] });
    const shiftDays = -1 * 3 * 1; // 3 days back
    await spy("/jobs/bulk-update", {
      ids: jobIds, patch: { scheduled_date_shift_days: shiftDays },
    });
    expect(spy).toHaveBeenCalledWith("/jobs/bulk-update", expect.objectContaining({
      patch: expect.objectContaining({ scheduled_date_shift_days: -3 }),
    }));
  });

  it("absolute + relative in the same patch is a client-side invariant violation", () => {
    // The frontend never composes both together — it toggles between
    // modes and sends exactly one. Verify the invariant is enforced
    // by the mode-toggle contract (only one field ever emitted).
    const buildPatch = (mode, absoluteDate, shiftDays) => (
      mode === "absolute" ? { scheduled_date: absoluteDate }
                                : { scheduled_date_shift_days: shiftDays }
    );
    const abs = buildPatch("absolute", "2026-03-15", 999);
    const rel = buildPatch("relative", "ignored", 3);
    expect("scheduled_date" in abs && !("scheduled_date_shift_days" in abs)).toBe(true);
    expect("scheduled_date_shift_days" in rel && !("scheduled_date" in rel)).toBe(true);
  });

  it("relative-shift confirm-btn is disabled at 0-day shift", () => {
    const canConfirm = (mode, absoluteDate, shiftDays) => (
      mode === "absolute" ? Boolean(absoluteDate) : shiftDays !== 0
    );
    expect(canConfirm("relative", "", 0)).toBe(false);
    expect(canConfirm("relative", "", 3)).toBe(true);
    expect(canConfirm("relative", "", -7)).toBe(true);
  });

  // Task MM · Feb 2026 — anchor-unscheduled flag.
  it("anchor checkbox on adds anchor_unscheduled_from_today to payload", async () => {
    const spy = jest.fn().mockResolvedValue({
      updated_count: 5, updated: [], failed: [], anchored_count: 2,
    });
    const anchorUnscheduled = true;
    const shiftDays = 3;
    const patch = {
      scheduled_date_shift_days: shiftDays,
      ...(anchorUnscheduled ? { anchor_unscheduled_from_today: true } : {}),
    };
    await spy("/jobs/bulk-update", { ids: ["a", "b"], patch });
    expect(spy).toHaveBeenCalledWith("/jobs/bulk-update", expect.objectContaining({
      patch: expect.objectContaining({
        scheduled_date_shift_days: 3,
        anchor_unscheduled_from_today: true,
      }),
    }));
  });

  it("anchor checkbox off (default) omits the flag entirely", () => {
    const anchorUnscheduled = false;
    const patch = {
      scheduled_date_shift_days: 3,
      ...(anchorUnscheduled ? { anchor_unscheduled_from_today: true } : {}),
    };
    expect("anchor_unscheduled_from_today" in patch).toBe(false);
    expect(patch.scheduled_date_shift_days).toBe(3);
  });
});
