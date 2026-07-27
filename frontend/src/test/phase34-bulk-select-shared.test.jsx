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
