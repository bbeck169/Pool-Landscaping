/**
 * Phase P4 · Feb-2026 — Recurring Jobs · Category Dropdowns on
 * Edit Modal.
 *
 * Covers:
 *   1. Both dropdowns fetch in parallel + populate on modal open.
 *   2. Pre-select the row's existing ``service_category_id`` /
 *      ``income_category_id`` on open.
 *   3. Empty-collection → disabled dropdown with the "No
 *      categories defined" placeholder (no crash).
 *   4. Save PATCH carries both ids (or explicit ``null`` when the
 *      user picks "— None —").
 *   5. 422 with ``code=service_category_invalid`` renders the
 *      per-field error and does NOT close the modal.
 *   6. Per-endpoint failure — one dropdown errors, the other
 *      still loads.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { getSpy, delSpy, postSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  delSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    del: (...a) => delSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn(),
  }),
}));
vi.mock("@/theme", () => ({
  colors: {
    brand: "#0284C7", onBrand: "#FFFFFF", onSurface: "#111827",
    onSurfaceInverse: "#FFFFFF", onBrandTertiary: "#0F172A",
    brandTertiary: "#E0F2FE", muted: "#6B7280",
    border: "#E5E7EB", surface: "#FFFFFF",
    surfaceSecondary: "#F8FAFC", searchIcon: "#0284C7",
    error: "#B91C1C",
  },
}));
vi.mock("@/components/customers/CustomerCombobox", () => ({
  default: () => null,
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: "admin", effectiveRole: "admin", can: () => true,
    loading: false, matrix: {}, previewRole: null,
    setPreviewRole: () => {}, isPreviewing: false, canPreview: false,
  }),
}));


import RecurringJobs from "@/pages/admin/RecurringJobs";


const SVC_LIST = [
  { id: "svc-1", name: "Weekly Service", is_archived: false },
  { id: "svc-2", name: "One-off", is_archived: false },
  { id: "svc-archived", name: "Retired", is_archived: true },  // filtered
];
const INC_LIST = [
  { id: "inc-1", name: "Pool Income", is_archived: false },
  { id: "inc-2", name: "Landscaping Income", is_archived: false },
];
const BASE_ROW = {
  id: "row-p4",
  customer_id: "cust-p4",
  customer_name: "P4 Cust",
  service_type: "Weekly Pool",
  frequency: "weekly", day_of_week: 0,
  start_date: "2026-02-02",
  price_cents: 12000,
  active: true, is_active: true,
  service_category_id: "svc-1",
  income_category_id: "inc-2",
  upcoming: [],
};


// ── Shared getSpy stub — resolves each endpoint the page hits at
// startup + the two category endpoints Phase P4 introduces.
function _makeGetImpl({ svcOverride, incOverride,
                            svcRejects = false, incRejects = false } = {}) {
  return async (path) => {
    if (path === "/service-categories") {
      if (svcRejects) throw new Error("boom svc");
      return { items: svcOverride ?? SVC_LIST, total: SVC_LIST.length };
    }
    if (path === "/income-categories") {
      if (incRejects) throw new Error("boom inc");
      return { items: incOverride ?? INC_LIST, total: INC_LIST.length };
    }
    if (path === "/recurring-jobs" || path.startsWith("/recurring-jobs?")) return { items: [BASE_ROW] };
    if (path.startsWith("/customers")) return { items: [] };
    if (path === "/technicians") return { items: [] };
    if (path === "/crews") return { items: [] };
    if (path === "/recurring-jobs/orphans") return { count: 0, items: [] };
    return null;
  };
}


beforeEach(() => {
  getSpy.mockReset();
  delSpy.mockReset();
  postSpy.mockReset();
  patchSpy.mockReset();
  getSpy.mockImplementation(_makeGetImpl());
  patchSpy.mockResolvedValue({ ...BASE_ROW });
  delSpy.mockResolvedValue({ ok: true });
});


const mount = () =>
  render(<MemoryRouter><RecurringJobs /></MemoryRouter>);


// ─────────────────────────────────────────────────────────────
// 1 · Populate + pre-select on open
// ─────────────────────────────────────────────────────────────
describe("Phase P4 · category dropdowns populate + pre-select on open", () => {
  it("fetches both endpoints in parallel and populates the two dropdowns", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("recurring-job-row-row-p4"));

    // Both dropdowns rendered by testid.
    const svc = await screen.findByTestId("recurring-jobs-service-category");
    const inc = await screen.findByTestId("recurring-jobs-income-category");
    expect(svc).toBeTruthy();
    expect(inc).toBeTruthy();

    // Archived rows filtered out.
    expect(Array.from(svc.querySelectorAll("option")).map((o) => o.value))
      .toEqual(["", "svc-1", "svc-2"]);
    expect(Array.from(inc.querySelectorAll("option")).map((o) => o.value))
      .toEqual(["", "inc-1", "inc-2"]);

    // Both endpoints hit at least once.
    expect(getSpy).toHaveBeenCalledWith("/service-categories");
    expect(getSpy).toHaveBeenCalledWith("/income-categories");
  });

  it("pre-selects the row's current values on open", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("recurring-job-row-row-p4"));

    const svc = await screen.findByTestId("recurring-jobs-service-category");
    const inc = await screen.findByTestId("recurring-jobs-income-category");
    // BASE_ROW: service_category_id = "svc-1", income_category_id = "inc-2".
    expect(svc.value).toBe("svc-1");
    expect(inc.value).toBe("inc-2");
  });

  it("first option is '— None —' and clears the field on select", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("recurring-job-row-row-p4"));
    const svc = await screen.findByTestId("recurring-jobs-service-category");
    // First option is the blank "— None —" clearer.
    const first = svc.querySelectorAll("option")[0];
    expect(first.value).toBe("");
    expect(first.textContent).toMatch(/None/);
    // Selecting it changes the current value to "".
    fireEvent.change(svc, { target: { value: "" } });
    expect(svc.value).toBe("");
  });
});


// ─────────────────────────────────────────────────────────────
// 2 · Empty-collection disabled state
// ─────────────────────────────────────────────────────────────
describe("Phase P4 · empty-collection disabled state", () => {
  it("shows a disabled dropdown with the admin-hint placeholder when a tenant has zero rows", async () => {
    getSpy.mockImplementation(_makeGetImpl({ svcOverride: [] }));
    mount();
    fireEvent.click(await screen.findByTestId("recurring-job-row-row-p4"));

    const svc = await screen.findByTestId("recurring-jobs-service-category");
    expect(svc).toBeTruthy();
    expect(svc.disabled).toBe(true);
    expect(svc.textContent).toMatch(/No categories defined/i);

    // The OTHER dropdown must still work — one empty collection
    // must not blank out the whole row.
    const inc = await screen.findByTestId("recurring-jobs-income-category");
    expect(inc.disabled).toBe(false);
    expect(Array.from(inc.querySelectorAll("option")).length)
      .toBeGreaterThan(1);
  });
});


// ─────────────────────────────────────────────────────────────
// 3 · Save carries both ids (+ clear-to-null)
// ─────────────────────────────────────────────────────────────
describe("Phase P4 · Save PATCH carries both ids", () => {
  it("sends the picked service_category_id and income_category_id", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("recurring-job-row-row-p4"));

    // Change both.
    fireEvent.change(
      await screen.findByTestId("recurring-jobs-service-category"),
      { target: { value: "svc-2" } },
    );
    fireEvent.change(
      screen.getByTestId("recurring-jobs-income-category"),
      { target: { value: "inc-1" } },
    );

    fireEvent.click(screen.getByTestId("recurring-jobs-save"));
    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    const [url, body] = patchSpy.mock.calls[0];
    expect(url).toBe("/recurring-jobs/row-p4");
    expect(body.service_category_id).toBe("svc-2");
    expect(body.income_category_id).toBe("inc-1");
  });

  it("sends null on both fields when the user picks '— None —'", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("recurring-job-row-row-p4"));

    fireEvent.change(
      await screen.findByTestId("recurring-jobs-service-category"),
      { target: { value: "" } },
    );
    fireEvent.change(
      screen.getByTestId("recurring-jobs-income-category"),
      { target: { value: "" } },
    );
    fireEvent.click(screen.getByTestId("recurring-jobs-save"));

    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    const body = patchSpy.mock.calls[0][1];
    expect(body.service_category_id).toBeNull();
    expect(body.income_category_id).toBeNull();
  });
});


// ─────────────────────────────────────────────────────────────
// 4 · 422 renders per-field error, modal stays open
// ─────────────────────────────────────────────────────────────
describe("Phase P4 · 422 per-field error surfaces without closing the modal", () => {
  it("service_category_invalid → inline error next to the service dropdown", async () => {
    // Stub PATCH to reject with the P4 422 body shape.
    patchSpy.mockRejectedValueOnce(Object.assign(new Error("Unprocessable"), {
      status: 422,
      body: {
        detail: {
          code: "service_category_invalid",
          field: "service_category_id",
          attempted: "hacked-id",
          collection: "service_categories",
        },
      },
    }));

    mount();
    fireEvent.click(await screen.findByTestId("recurring-job-row-row-p4"));
    fireEvent.click(await screen.findByTestId("recurring-jobs-save"));

    // Per-field error rendered.
    const err = await screen.findByTestId(
      "recurring-jobs-service-category-save-error");
    expect(err.textContent).toMatch(/Invalid/i);
    // Modal is still open (Save button still in the DOM).
    expect(screen.getByTestId("recurring-jobs-save")).toBeInTheDocument();
    // The INCOME error slot did NOT render — only the offending
    // field's error surfaces.
    expect(screen.queryByTestId("recurring-jobs-income-category-save-error"))
      .toBeNull();
  });

  it("income_category_invalid → inline error next to the income dropdown", async () => {
    patchSpy.mockRejectedValueOnce(Object.assign(new Error("Unprocessable"), {
      status: 422,
      body: {
        detail: {
          code: "income_category_invalid",
          field: "income_category_id",
          attempted: "hacked-id",
          collection: "income_categories",
        },
      },
    }));

    mount();
    fireEvent.click(await screen.findByTestId("recurring-job-row-row-p4"));
    fireEvent.click(await screen.findByTestId("recurring-jobs-save"));

    const err = await screen.findByTestId(
      "recurring-jobs-income-category-save-error");
    expect(err.textContent).toMatch(/Invalid/i);
    expect(screen.getByTestId("recurring-jobs-save")).toBeInTheDocument();
  });
});


// ─────────────────────────────────────────────────────────────
// 5 · Per-endpoint fetch failure is isolated
// ─────────────────────────────────────────────────────────────
describe("Phase P4 · one endpoint failure does NOT hide the other dropdown", () => {
  it("service endpoint rejects → error state on service, income dropdown still loads", async () => {
    getSpy.mockImplementation(_makeGetImpl({ svcRejects: true }));
    mount();
    fireEvent.click(await screen.findByTestId("recurring-job-row-row-p4"));

    // Service side renders the retry link, not a select.
    const svcErr = await screen.findByTestId(
      "recurring-jobs-service-category-error");
    expect(svcErr.textContent).toMatch(/Failed to load/i);
    expect(screen.getByTestId("recurring-jobs-service-category-retry"))
      .toBeInTheDocument();

    // Income side renders normally.
    const inc = await screen.findByTestId("recurring-jobs-income-category");
    expect(inc.disabled).toBe(false);
    expect(Array.from(inc.querySelectorAll("option")).map((o) => o.value))
      .toEqual(["", "inc-1", "inc-2"]);
  });
});
