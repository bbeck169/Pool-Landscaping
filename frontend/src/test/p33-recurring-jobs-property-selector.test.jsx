/**
 * Phase P33 · Feb-2026 — Recurring-Jobs modal property selector.
 *
 * Locks in the Least-Click 0/1/2+ property-selector semantics that
 * mirror ``pages/jobs/JobNew.jsx``:
 *
 *   * 0 properties → inline warning + Save disabled.
 *   * 1 property   → auto-selected; read-only label; no dropdown.
 *   * 2+           → required <select>; Save disabled until pick.
 *   * Customer switch → property state resets, ladder re-runs.
 *   * Edit-mode pre-hydration → dropdown pre-selects the row's
 *     ``property_id`` when the customer owns it.
 */
import React from "react";
import {
  render, screen, fireEvent, waitFor, within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";


let _apiGet = vi.fn();
let _apiPost = vi.fn();
let _apiPatch = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (path, ...rest) => _apiGet(path, ...rest),
    post: (path, ...rest) => _apiPost(path, ...rest),
    patch: (path, ...rest) => _apiPatch(path, ...rest),
    delete: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
  },
}));

// The CustomerCombobox is a heavyweight combobox — swap for a bare
// <select> in tests so we can drive the customer-pick side-effect
// without simulating typeahead keystrokes.
vi.mock("@/components/customers/CustomerCombobox", () => ({
  default: ({ value, onChange, customers, testid }) => (
    <select data-testid={testid || "cust-picker"}
             value={value || ""}
             onChange={(e) => onChange(e.target.value)}>
      <option value="">— pick customer —</option>
      {(customers || []).map((c) => (
        <option key={c.id} value={c.id}>{c.name}</option>
      ))}
    </select>
  ),
}));

// MasterServiceCombobox → stubbed to a plain input so the modal
// mounts without needing the shared services collection.
vi.mock("@/components/services/MasterServiceCombobox", () => ({
  default: ({ value, onChange }) => (
    <input data-testid="svc-combo"
             value={value || ""}
             onChange={(e) => onChange({
               name: e.target.value, default_price: null, category: null,
             })} />
  ),
}));

// Toast surface — we just need it not to explode.
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), info: vi.fn(),
  }),
}));

vi.mock("@/hooks/use-toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));


const CUSTS = [
  { id: "c-zero", name: "Zero Props" },
  { id: "c-one", name: "Solo Prop" },
  { id: "c-many", name: "Multi Props" },
];

const PROPS_BY_CUST = {
  "c-zero": [],
  "c-one": [
    { id: "p-solo", label: "Home", active: true,
       address: { line1: "1 Only St" } },
  ],
  "c-many": [
    { id: "p-1", label: "Home", active: true,
       address: { line1: "1 Main St" }, sort_order: 0 },
    { id: "p-2", label: "Vacation", active: true,
       address: { line1: "9 Beach Rd" }, sort_order: 1 },
    { id: "p-3", label: "Rental", active: true,
       address: { line1: "45 Elm Ave" }, sort_order: 2 },
  ],
};


function _setupApi({
  overrideProperties = null,
  overrideList = null,
} = {}) {
  _apiGet = vi.fn().mockImplementation((path) => {
    if (path.startsWith("/customers/") && path.endsWith("/properties")) {
      const cid = path.split("/")[2];
      if (overrideProperties && cid in overrideProperties) {
        return Promise.resolve(overrideProperties[cid]);
      }
      return Promise.resolve(PROPS_BY_CUST[cid] || []);
    }
    if (path.startsWith("/customers")) {
      return Promise.resolve({ items: CUSTS, total: CUSTS.length });
    }
    if (path.startsWith("/recurring-jobs/orphans")
        || path.startsWith("/recurring-jobs/purge-orphans-preview")) {
      return Promise.resolve({ orphans: [], count: 0 });
    }
    if (path.startsWith("/recurring-jobs")) {
      const rows = overrideList ?? [];
      return Promise.resolve({
        items: rows,
        counts: { active: rows.length, paused: 0, total: rows.length },
        total: rows.length,
      });
    }
    if (path.startsWith("/technicians") || path.startsWith("/crews")
        || path.startsWith("/tenants") || path.startsWith("/service-categories")
        || path.startsWith("/income-categories")) {
      return Promise.resolve([]);
    }
    return Promise.resolve({});
  });
  _apiPost = vi.fn().mockResolvedValue({});
  _apiPatch = vi.fn().mockResolvedValue({});
}


async function _mountAndOpenCreate() {
  const { default: RecurringJobs } = await import(
    "@/pages/admin/RecurringJobs"
  );
  const utils = render(
    <MemoryRouter><RecurringJobs /></MemoryRouter>,
  );
  // Wait for initial hydration.
  await waitFor(() => {
    // NEW toolbar button opens the create modal.
    expect(document.body.textContent).toMatch(/new|create/i);
  });
  // Trigger the create modal via the toolbar. Grep the page for a
  // testid that stably opens it; fall back to clicking the visible
  // "+ New" / "Create" button.
  const openBtn = screen.queryByTestId("recurring-jobs-new-btn")
    || Array.from(document.querySelectorAll("button")).find(
        (b) => /new|create/i.test(b.textContent),
      );
  fireEvent.click(openBtn);
  await waitFor(() => {
    expect(screen.getByTestId("recurring-jobs-customer"))
      .toBeInTheDocument();
  });
  return utils;
}


describe("P33 · RecurringJobs modal property selector", () => {
  beforeEach(() => { _setupApi(); });

  it("0-property customer shows warning + hides property picker",
      async () => {
    await _mountAndOpenCreate();
    fireEvent.change(screen.getByTestId("recurring-jobs-customer"), {
      target: { value: "c-zero" },
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("recurring-jobs-property-empty-warning"),
      ).toBeInTheDocument();
    });
    expect(screen.getByTestId("recurring-jobs-property-empty-warning")
      .textContent).toMatch(/no addresses on file/i);
    // No dropdown affordance for a zero-property customer.
    expect(
      screen.queryByTestId("recurring-jobs-property-select"),
    ).toBeNull();
    expect(
      screen.queryByTestId("recurring-jobs-property-single"),
    ).toBeNull();
    // Save button disabled by the propertyGateOk clause.
    const save = screen.getByTestId("recurring-jobs-save");
    expect(save).toBeDisabled();
  });

  it("1-property customer auto-selects + shows read-only label + no dropdown",
      async () => {
    await _mountAndOpenCreate();
    fireEvent.change(screen.getByTestId("recurring-jobs-customer"), {
      target: { value: "c-one" },
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("recurring-jobs-property-single"),
      ).toBeInTheDocument();
    });
    const label = screen.getByTestId("recurring-jobs-property-single");
    expect(label.textContent).toMatch(/Home/);
    expect(label.textContent).toMatch(/1 Only St/);
    // No <select> visible for the 1-property case.
    expect(
      screen.queryByTestId("recurring-jobs-property-select"),
    ).toBeNull();
    // Save NOT disabled by property gate (still requires other
    // fields — grep for the disabled state and verify property is
    // not the reason).
    const save = screen.getByTestId("recurring-jobs-save");
    // service_type is still empty on a fresh modal, so save may be
    // disabled — but flipping the empty-warning test we can assert
    // the property gate is NOT the blocker by asserting no warning
    // is rendered.
    expect(
      screen.queryByTestId("recurring-jobs-property-empty-warning"),
    ).toBeNull();
    expect(
      screen.queryByTestId("recurring-jobs-property-required"),
    ).toBeNull();
  });

  it("3-property customer shows required dropdown; Save gated on pick",
      async () => {
    await _mountAndOpenCreate();
    fireEvent.change(screen.getByTestId("recurring-jobs-customer"), {
      target: { value: "c-many" },
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("recurring-jobs-property-select"),
      ).toBeInTheDocument();
    });
    const sel = screen.getByTestId("recurring-jobs-property-select");
    // Not yet picked → required message is shown.
    expect(
      screen.getByTestId("recurring-jobs-property-required"),
    ).toBeInTheDocument();
    // Save is disabled (property_id null).
    expect(screen.getByTestId("recurring-jobs-save")).toBeDisabled();
    // Pick one — required-message goes away.
    fireEvent.change(sel, { target: { value: "p-2" } });
    await waitFor(() => {
      expect(
        screen.queryByTestId("recurring-jobs-property-required"),
      ).toBeNull();
    });
    // Verify all three options are rendered.
    const options = within(sel).getAllByRole("option");
    // includes the placeholder "Choose a property…" + 3 real.
    expect(options.length).toBe(4);
  });

  it("customer switch resets property state (1-prop → 3-prop)",
      async () => {
    await _mountAndOpenCreate();
    // First pick — 1-prop customer, auto-select.
    fireEvent.change(screen.getByTestId("recurring-jobs-customer"), {
      target: { value: "c-one" },
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("recurring-jobs-property-single"),
      ).toBeInTheDocument();
    });
    // Switch to the 3-prop customer.
    fireEvent.change(screen.getByTestId("recurring-jobs-customer"), {
      target: { value: "c-many" },
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("recurring-jobs-property-select"),
      ).toBeInTheDocument();
    });
    // The old single-label MUST be gone AND the multi-select
    // starts with the placeholder (property_id was reset).
    expect(
      screen.queryByTestId("recurring-jobs-property-single"),
    ).toBeNull();
    const sel = screen.getByTestId("recurring-jobs-property-select");
    expect(sel.value).toBe("");
    // Required warning surfaces because property_id is now null.
    expect(
      screen.getByTestId("recurring-jobs-property-required"),
    ).toBeInTheDocument();
  });

  it("edit-mode pre-selects property_id when the customer owns it",
      async () => {
    _setupApi({
      overrideList: [{
        id: "tpl-edit-1",
        customer_id: "c-many",
        customer_name: "Multi Props",
        service_type: "Pool Cleaning",
        frequency: "weekly", day_of_week: 1,
        price_cents: 15000,
        active: true, is_active: true,
        recurrence_never_ends: true, end_date: null,
        property_id: "p-2",
      }],
    });
    const { default: RecurringJobs } = await import(
      "@/pages/admin/RecurringJobs"
    );
    render(<MemoryRouter><RecurringJobs /></MemoryRouter>);
    // Wait for the list row to render, then click it → openEdit.
    // The row's testid pattern is
    // ``recurring-job-row-<template_id>`` (grep line 1179 of
    // ``pages/admin/RecurringJobs.jsx``).
    await waitFor(() => {
      expect(
        screen.getByTestId("recurring-job-row-tpl-edit-1"),
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("recurring-job-row-tpl-edit-1"));
    await waitFor(() => {
      expect(
        screen.getByTestId("recurring-jobs-property-select"),
      ).toBeInTheDocument();
    });
    const sel = screen.getByTestId("recurring-jobs-property-select");
    expect(sel.value).toBe("p-2");
    // Required-warning MUST NOT be visible (already picked).
    expect(
      screen.queryByTestId("recurring-jobs-property-required"),
    ).toBeNull();
  });
});
