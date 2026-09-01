/**
 * Phase H9 · Feb-2026 — Recurring job edit modal tests.
 * Focus: free-typing price + combined tech/crew dropdown.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(),
          patch: vi.fn(), put: vi.fn(), del: vi.fn() },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { api } from "@/api";
import RecurringJobs from "@/pages/admin/RecurringJobs";


const CUSTOMERS = [{ id: "cust-1", name: "Test Cust" }];
const TECHS = [
  { id: "tech-a", name: "Alice" },
  { id: "tech-b", name: "Bob" },
];
const CREWS = [
  { id: "crew-blue", name: "Blue Crew" },
  { id: "crew-green", name: "Green Crew" },
];
const EXISTING_ROW = {
  id: "row-1",
  customer_id: "cust-1", customer_name: "Test Cust",
  service_type: "Weekly service",
  frequency: "weekly", day_of_week: 0,
  start_date: "2026-02-02", end_date: null,
  recurrence_never_ends: true,
  price_cents: 12000,
  assigned_tech_id: "tech-a",
  crew_id: null, crew_name: null,
  active: true, allow_sunday: false,
  notes: "",
};


beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((path) => {
    if (path.startsWith("/recurring-jobs")) return Promise.resolve({ items: [EXISTING_ROW] });
    if (path.startsWith("/customers")) return Promise.resolve({ items: CUSTOMERS });
    if (path.startsWith("/technicians")) return Promise.resolve(TECHS);
    if (path.startsWith("/crews")) return Promise.resolve({ items: CREWS });
    return Promise.resolve({});
  });
  api.patch.mockResolvedValue({ ...EXISTING_ROW });
});


const renderPage = () =>
  render(<MemoryRouter><RecurringJobs /></MemoryRouter>);


async function openEditModal() {
  renderPage();
  // Wait for the row to actually render (initial load fires the
  // `/recurring-jobs` GET which resolves via the mock).
  const editBtn = await screen.findByTestId(
    "recurring-job-edit-row-1",
    {}, { timeout: 3000 },
  );
  fireEvent.click(editBtn);
  await waitFor(() =>
    expect(screen.getByTestId("recurring-jobs-price")).toBeInTheDocument(),
  );
}


describe("H9 · Recurring Edit modal — price + assignment", () => {
  it("price input is type=text with inputMode=decimal (no spinner)",
     async () => {
    await openEditModal();
    const price = screen.getByTestId("recurring-jobs-price");
    expect(price.getAttribute("type")).toBe("text");
    expect(price.getAttribute("inputMode")).toBe("decimal");
    // Pre-fill from price_cents ÷ 100 with .toFixed(2).
    expect(price.value).toBe("120.00");
  });

  it("invalid price shows inline error and disables Save", async () => {
    await openEditModal();
    const price = screen.getByTestId("recurring-jobs-price");
    fireEvent.change(price, { target: { value: "abc" } });
    await waitFor(() =>
      expect(screen.getByTestId("recurring-jobs-price-error")).toBeInTheDocument(),
    );
    const save = screen.getByTestId("recurring-jobs-save");
    expect(save.hasAttribute("disabled")).toBe(true);
    // Fix the price → error clears, save re-enables.
    fireEvent.change(price, { target: { value: "42.50" } });
    await waitFor(() =>
      expect(screen.queryByTestId("recurring-jobs-price-error")).toBeNull(),
    );
    expect(screen.getByTestId("recurring-jobs-save").hasAttribute("disabled")).toBe(false);
  });

  it("valid decimal price saves with price_cents (rounded to cents)",
     async () => {
    await openEditModal();
    const price = screen.getByTestId("recurring-jobs-price");
    fireEvent.change(price, { target: { value: "42.5" } });
    fireEvent.blur(price);
    // Blur normalizes to .toFixed(2).
    expect(price.value).toBe("42.50");
    fireEvent.click(screen.getByTestId("recurring-jobs-save"));
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    const [url, body] = api.patch.mock.calls[0];
    expect(url).toBe("/recurring-jobs/row-1");
    expect(body.price_cents).toBe(4250);
  });

  it("assignment dropdown lists both techs and crews", async () => {
    await openEditModal();
    const sel = await screen.findByTestId("recurring-jobs-assign");
    // Techs optgroup renders both tech rows.
    expect(sel.querySelector(
      '[data-testid="recurring-jobs-assign-tech-tech-a"]',
    )).not.toBeNull();
    expect(sel.querySelector(
      '[data-testid="recurring-jobs-assign-tech-tech-b"]',
    )).not.toBeNull();
    // Crews optgroup renders both crew rows.
    const crewBlue = sel.querySelector(
      '[data-testid="recurring-jobs-assign-crew-crew-blue"]',
    );
    expect(crewBlue).not.toBeNull();
    // Disambiguation prefix — "Crew: <name>".
    expect(crewBlue.textContent).toMatch(/^Crew:\s*Blue Crew/);
    // Auto-assign is the ""-value option.
    expect(sel.querySelector(
      '[data-testid="recurring-jobs-assign-auto"]',
    )).not.toBeNull();
  });

  it("selecting a crew clears assigned_tech_id in the save payload",
     async () => {
    await openEditModal();
    const sel = screen.getByTestId("recurring-jobs-assign");
    fireEvent.change(sel, { target: { value: "crew:crew-blue" } });
    fireEvent.click(screen.getByTestId("recurring-jobs-save"));
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    const body = api.patch.mock.calls[0][1];
    expect(body.crew_id).toBe("crew-blue");
    expect(body.assigned_tech_id).toBeNull();
  });

  it("selecting a tech clears crew_id in the save payload", async () => {
    // Seed the row with a crew already set so the flip is meaningful.
    api.get.mockImplementation((path) => {
      if (path.startsWith("/recurring-jobs")) return Promise.resolve({
        items: [{ ...EXISTING_ROW, assigned_tech_id: null,
                   crew_id: "crew-green",
                   crew_name: "Green Crew" }],
      });
      if (path.startsWith("/customers")) return Promise.resolve({ items: CUSTOMERS });
      if (path.startsWith("/technicians")) return Promise.resolve(TECHS);
      if (path.startsWith("/crews")) return Promise.resolve({ items: CREWS });
      return Promise.resolve({});
    });
    await openEditModal();
    const sel = screen.getByTestId("recurring-jobs-assign");
    fireEvent.change(sel, { target: { value: "tech:tech-b" } });
    fireEvent.click(screen.getByTestId("recurring-jobs-save"));
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    const body = api.patch.mock.calls[0][1];
    expect(body.assigned_tech_id).toBe("tech-b");
    expect(body.crew_id).toBeNull();
  });

  it("'Auto-assign' clears both crew_id and assigned_tech_id",
     async () => {
    await openEditModal();
    const sel = screen.getByTestId("recurring-jobs-assign");
    fireEvent.change(sel, { target: { value: "" } });
    fireEvent.click(screen.getByTestId("recurring-jobs-save"));
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    const body = api.patch.mock.calls[0][1];
    expect(body.assigned_tech_id).toBeNull();
    expect(body.crew_id).toBeNull();
  });
});
