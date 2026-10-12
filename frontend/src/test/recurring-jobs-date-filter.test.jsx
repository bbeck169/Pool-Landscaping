/**
 * Feb-2026 · Recurring Jobs date-range filter (P1 brief).
 *
 * Locks the "Next" column filter behavior added in commit
 * 52c3eb6fa — presets cherry-pick the shared resolver module and
 * compose with the existing search + category filters under AND
 * semantics. Mocks the page's API layer so the test exercises just
 * the filter wiring, not the live backend.
 *
 * Cases:
 *   1. Preset "Today" shows only rows whose upcoming[0] === today.
 *   2. Preset "Next 7 Days" shows the inclusive 7-day window.
 *   3. Custom range (manual start/end) is inclusive at both ends.
 *   4. Composes with search filter — AND semantics.
 *   5. Default (no range) shows all rows (incl. rows with empty
 *      upcoming[]).
 *   6. Clear button restores all rows and removes the active chip.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, within, cleanup, waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { addDays, format, startOfDay, startOfWeek, endOfWeek,
          startOfMonth, endOfMonth } from "date-fns";


// ── Mocks ────────────────────────────────────────────────────────
const getMock = vi.fn();
const postMock = vi.fn();
const patchMock = vi.fn();
const delMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...args) => getMock(...args),
    post: (...args) => postMock(...args),
    patch: (...args) => patchMock(...args),
    del: (...args) => delMock(...args),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: (m) => toastSuccess(m), error: (m) => toastError(m) },
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ role: "admin" }),
}));
// react-i18next double — returns the fallback string so visible
// copy ("Search by customer…") matches regardless of locale.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (_k, fallback) => fallback || _k }),
}));
vi.mock("@/components/customers/CustomerCombobox", () => ({
  default: () => <div data-testid="customer-combobox-stub" />,
}));
vi.mock("@/components/recurring/MonthlyNthWeekdaySelector", () => ({
  MonthlyNthWeekdaySelector: () => <div />,
}));
vi.mock("@/components/recurring/CategoryComboCell", () => ({
  default: () => <div />,
}));
vi.mock("@/components/services/MasterServiceCombobox", () => ({
  default: () => <div />,
}));
vi.mock("@/components/customer", () => ({
  CustomerLink: ({ name }) => <span>{name}</span>,
  PhoneLink: ({ children }) => <span>{children}</span>,
}));


// Import AFTER mocks so the module resolves them correctly.
import RecurringJobs from "../pages/admin/RecurringJobs";


// ── Fixtures ─────────────────────────────────────────────────────
const TODAY = startOfDay(new Date());
const iso = (d) => format(d, "yyyy-MM-dd");


function mkTemplate(id, customer_name, upcoming0) {
  // Only the fields the filtered-view / table render actually read.
  return {
    id, customer_name, customer_company_name: "", customer_email: "",
    customer_phone: "", customer_id: `c-${id}`,
    service_type: `svc-${id}`, service_category_id: null,
    frequency: "weekly", price_cents: 10000,
    start_date: iso(TODAY),
    end_date: null,
    is_active: true, active: true, recurrence_never_ends: true,
    assigned_tech_id: null, crew_id: null, crew_name: null,
    day_of_week: 1, day_of_month: null, monthly_pattern: "day_of_month",
    monthly_weekday: null, monthly_nth_week: null,
    allow_sunday: true, interval_days: null,
    notes: "", upcoming: upcoming0 ? [upcoming0] : [],
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00",
    tenant_id: "t1",
  };
}


const ROWS = [
  mkTemplate("today",       "Alpha Pools",   iso(TODAY)),
  mkTemplate("tomorrow",    "Beta Service",  iso(addDays(TODAY, 1))),
  mkTemplate("day_plus_6",  "Gamma Garden",  iso(addDays(TODAY, 6))),
  mkTemplate("day_plus_7",  "Delta Deck",    iso(addDays(TODAY, 7))),
  mkTemplate("day_plus_20", "Echo Equipment",iso(addDays(TODAY, 20))),
  mkTemplate("day_plus_45", "Foxtrot Field", iso(addDays(TODAY, 45))),
  mkTemplate("no_upcoming", "Golf Grounds",  null),
];


// Default API handler — returns the full row set.
function defaultGet(url) {
  if (url.startsWith("/recurring-jobs?status=")) {
    return Promise.resolve({ items: ROWS, counts: { active: 7, paused: 0, total: 7 } });
  }
  if (url.startsWith("/customers")) return Promise.resolve({ items: [] });
  if (url.startsWith("/technicians")) return Promise.resolve([]);
  if (url.startsWith("/crews")) return Promise.resolve([]);
  if (url.startsWith("/service-categories")) return Promise.resolve({ items: [] });
  if (url.startsWith("/income-categories")) return Promise.resolve({ items: [] });
  if (url.startsWith("/recurring-jobs/orphans")) return Promise.resolve({ orphan_count: 0 });
  if (url.startsWith("/recurring-jobs/purge-orphans-preview")) return Promise.resolve({ count: 0 });
  return Promise.resolve({});
}


async function renderPage() {
  const utils = render(
    <MemoryRouter initialEntries={["/admin/recurring-jobs"]}>
      <RecurringJobs />
    </MemoryRouter>,
  );
  // Wait for the first table render.
  await waitFor(() => {
    expect(screen.getByTestId("recurring-jobs-table")).toBeTruthy();
  });
  return utils;
}


function rowCount() {
  const table = screen.getByTestId("recurring-jobs-table");
  // Count <tr> inside <tbody> only.
  const tbody = table.querySelector("tbody");
  return tbody ? tbody.querySelectorAll("tr").length : 0;
}


// ── Suite ────────────────────────────────────────────────────────
describe("RecurringJobs · 'Next' column date-range filter", () => {
  beforeEach(() => {
    getMock.mockReset();
    getMock.mockImplementation(defaultGet);
    postMock.mockReset();
    patchMock.mockReset();
    delMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });
  afterEach(() => cleanup());


  it("default state (no range) shows every row including rows with no upcoming[]",
     async () => {
    await renderPage();
    // 7 rows total in the fixture.
    expect(rowCount()).toBe(7);
    // No active chip + no clear button.
    expect(
      screen.queryByTestId("recurring-jobs-date-clear"),
    ).toBeNull();
    for (const key of ["today", "this_week", "next_7_days",
                        "next_30_days", "this_month"]) {
      const btn = screen.getByTestId(`recurring-jobs-date-preset-${key}`);
      expect(btn.getAttribute("data-active")).toBe("false");
    }
  });


  it("preset 'Today' narrows to rows whose upcoming[0] equals today",
     async () => {
    await renderPage();
    fireEvent.click(screen.getByTestId("recurring-jobs-date-preset-today"));
    expect(rowCount()).toBe(1);
    expect(screen.getByText("Alpha Pools")).toBeTruthy();
    // Active state.
    expect(
      screen.getByTestId("recurring-jobs-date-preset-today")
        .getAttribute("data-active"),
    ).toBe("true");
    // Clear button appears.
    expect(screen.getByTestId("recurring-jobs-date-clear")).toBeTruthy();
  });


  it("preset 'Next 7 Days' is inclusive — today, +1, +6 all included; +7 excluded",
     async () => {
    await renderPage();
    fireEvent.click(
      screen.getByTestId("recurring-jobs-date-preset-next_7_days"),
    );
    // Includes today, +1, +6 ⇒ 3 rows (NOT +7 which is day 8 of a
    // 7-day inclusive window).
    expect(rowCount()).toBe(3);
    expect(screen.getByText("Alpha Pools")).toBeTruthy();
    expect(screen.getByText("Beta Service")).toBeTruthy();
    expect(screen.getByText("Gamma Garden")).toBeTruthy();
    expect(screen.queryByText("Delta Deck")).toBeNull();
    expect(screen.queryByText("Golf Grounds")).toBeNull();
  });


  it("custom start/end range is inclusive both ends",
     async () => {
    await renderPage();
    const start = iso(addDays(TODAY, 1));
    const end = iso(addDays(TODAY, 20));
    fireEvent.change(screen.getByTestId("recurring-jobs-date-start"),
                       { target: { value: start } });
    fireEvent.change(screen.getByTestId("recurring-jobs-date-end"),
                       { target: { value: end } });
    // +1, +6, +7, +20 included (4 rows). +0 (today) excluded,
    // +45 excluded, no_upcoming excluded.
    expect(rowCount()).toBe(4);
    expect(screen.queryByText("Alpha Pools")).toBeNull();
    expect(screen.getByText("Beta Service")).toBeTruthy();
    expect(screen.getByText("Gamma Garden")).toBeTruthy();
    expect(screen.getByText("Delta Deck")).toBeTruthy();
    expect(screen.getByText("Echo Equipment")).toBeTruthy();
    expect(screen.queryByText("Foxtrot Field")).toBeNull();
    expect(screen.queryByText("Golf Grounds")).toBeNull();
    // Setting custom range clears the preset-active state (chips
    // should all read inactive).
    for (const key of ["today", "this_week", "next_7_days",
                        "next_30_days", "this_month"]) {
      const btn = screen.getByTestId(`recurring-jobs-date-preset-${key}`);
      expect(btn.getAttribute("data-active")).toBe("false");
    }
  });


  it("composes with search filter under AND semantics",
     async () => {
    await renderPage();
    // Narrow to Next 30 Days first.
    fireEvent.click(
      screen.getByTestId("recurring-jobs-date-preset-next_30_days"),
    );
    // Rows in window: today, +1, +6, +7, +20 ⇒ 5 rows (no_upcoming
    // excluded, +45 excluded).
    expect(rowCount()).toBe(5);
    // Apply search "pools" → only Alpha Pools matches.
    const search = screen.getByTestId("recurring-search-input");
    fireEvent.change(search, { target: { value: "pools" } });
    // Debounce = 250ms in the page.
    await waitFor(
      () => expect(rowCount()).toBe(1),
      { timeout: 1000 },
    );
    expect(screen.getByText("Alpha Pools")).toBeTruthy();
  });


  it("clear button restores every row and removes the active chip",
     async () => {
    await renderPage();
    fireEvent.click(screen.getByTestId("recurring-jobs-date-preset-today"));
    expect(rowCount()).toBe(1);
    // Clear.
    fireEvent.click(screen.getByTestId("recurring-jobs-date-clear"));
    expect(rowCount()).toBe(7);
    // Button is gone when inactive.
    expect(
      screen.queryByTestId("recurring-jobs-date-clear"),
    ).toBeNull();
    expect(
      screen.getByTestId("recurring-jobs-date-preset-today")
        .getAttribute("data-active"),
    ).toBe("false");
  });
});
