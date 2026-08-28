/**
 * Feb 2026 · Dashboard global-search bar.
 *
 * Contract:
 *   * Input mounts on the Dashboard with testid
 *     ``dashboard-global-search`` and placeholder mentions the
 *     entity types.
 *   * Typing debounces ~300 ms then fires ``GET /api/search?q=...``.
 *   * Results panel groups matches under section headers
 *     ("Customers · N", "Jobs · N", ...).
 *   * Clicking a result navigates to that record's detail route.
 *   * Empty state renders when no matches; Esc + outside-click
 *     both close the panel.
 *
 * Real timers throughout — vitest fake timers break the
 * @testing-library/react ``waitFor`` polling loop. Default
 * timeout has plenty of headroom for the 300 ms debounce.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, waitFor, fireEvent,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  },
  TOKEN_KEY: "token",
}));


const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});


import GlobalSearchBar from "@/components/dashboard/GlobalSearchBar";


function mount() {
  return render(
    <MemoryRouter>
      <GlobalSearchBar />
    </MemoryRouter>,
  );
}


const CANNED = {
  customers: [
    { id: "c-1", primary: "Miguel Alvarez",   secondary: "miguel@example.com" },
    { id: "c-2", primary: "Miguel Rodriguez", secondary: "+1-555-0100" },
  ],
  jobs: [
    { id: "j-1", primary: "Weekly pool service", secondary: "Miguel Alvarez" },
  ],
  invoices: [
    { id: "inv-1", primary: "Invoice INV-2026-0007", secondary: "Miguel Alvarez · $420.00" },
  ],
  leads: [],
};


const WAIT = { timeout: 3000 };


describe("Dashboard · global search bar", () => {
  beforeEach(() => {
    getMock.mockReset();
    navigateMock.mockReset();
  });

  it("renders the input with the correct testid + placeholder", () => {
    mount();
    const input = screen.getByTestId("dashboard-global-search");
    expect(input).toBeInTheDocument();
    expect(input.getAttribute("placeholder") || "")
      .toMatch(/customers.*jobs.*invoices.*leads/i);
  });

  it("debounces and calls /search once, grouping results by entity", async () => {
    getMock.mockResolvedValue(CANNED);
    mount();
    fireEvent.change(screen.getByTestId("dashboard-global-search"),
                       { target: { value: "Miguel" } });
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(1), WAIT);
    expect(getMock.mock.calls[0][0]).toMatch(/^\/search\?q=Miguel(&|$)/);
    await screen.findByTestId("global-search-results");
    expect(screen.getByTestId("global-search-group-customers")).toBeInTheDocument();
    expect(screen.getByTestId("global-search-group-jobs")).toBeInTheDocument();
    expect(screen.getByTestId("global-search-group-invoices")).toBeInTheDocument();
    // Empty leads group does NOT render.
    expect(screen.queryByTestId("global-search-group-leads")).toBeNull();
    expect(screen.getByTestId("global-search-result-customers-c-1")).toBeInTheDocument();
    expect(screen.getByTestId("global-search-result-invoices-inv-1")).toBeInTheDocument();
  });

  it("clicking a result navigates to that record's detail route", async () => {
    getMock.mockResolvedValue(CANNED);
    mount();
    fireEvent.change(screen.getByTestId("dashboard-global-search"),
                       { target: { value: "Miguel" } });
    const row = await waitFor(
      () => screen.getByTestId("global-search-result-customers-c-1"),
      WAIT,
    );
    fireEvent.click(row);
    expect(navigateMock).toHaveBeenCalledWith("/customers/c-1");
  });

  it("clicking an invoice result navigates to /invoices/<id>", async () => {
    getMock.mockResolvedValue(CANNED);
    mount();
    fireEvent.change(screen.getByTestId("dashboard-global-search"),
                       { target: { value: "Miguel" } });
    const row = await waitFor(
      () => screen.getByTestId("global-search-result-invoices-inv-1"),
      WAIT,
    );
    fireEvent.click(row);
    expect(navigateMock).toHaveBeenCalledWith("/invoices/inv-1");
  });

  it("shows an empty state when the query returns zero rows across all entities", async () => {
    getMock.mockResolvedValue({ customers: [], jobs: [], invoices: [], leads: [] });
    mount();
    fireEvent.change(screen.getByTestId("dashboard-global-search"),
                       { target: { value: "zzz-unknown" } });
    const empty = await waitFor(
      () => screen.getByTestId("global-search-empty"),
      WAIT,
    );
    expect(empty.textContent || "").toMatch(/zzz-unknown/);
  });

  it("Esc closes the results panel", async () => {
    getMock.mockResolvedValue(CANNED);
    mount();
    const input = screen.getByTestId("dashboard-global-search");
    fireEvent.change(input, { target: { value: "Miguel" } });
    await waitFor(
      () => screen.getByTestId("global-search-results"),
      WAIT,
    );
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(
      () => expect(screen.queryByTestId("global-search-results")).toBeNull(),
      WAIT,
    );
  });

  it("clear button empties the input and closes the panel", async () => {
    getMock.mockResolvedValue(CANNED);
    mount();
    const input = screen.getByTestId("dashboard-global-search");
    fireEvent.change(input, { target: { value: "Miguel" } });
    await waitFor(
      () => screen.getByTestId("global-search-results"),
      WAIT,
    );
    fireEvent.click(screen.getByTestId("dashboard-global-search-clear"));
    await waitFor(() => {
      expect(input.value).toBe("");
      expect(screen.queryByTestId("global-search-results")).toBeNull();
    }, WAIT);
  });
});
