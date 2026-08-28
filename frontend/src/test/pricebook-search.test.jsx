/**
 * Feb 2026 · Pricebook · client-side search field.
 *
 * Contract:
 *   * Compact text input at the top of the Price Book list with
 *     testid ``pricebook-search-input``.
 *   * Case-insensitive substring match on ``name`` first, then
 *     ``category``, then ``unit``.
 *   * ~250 ms debounce.
 *   * Empty state renders when the debounced filter yields zero
 *     rows AND the query is non-empty (testid
 *     ``pricebook-search-empty``); a "Clear search" button
 *     (testid ``pricebook-search-clear``) restores the full list.
 *   * Sits AFTER the existing supplier filter — search stacks
 *     with it.
 *
 * Real timers throughout — vitest fake timers break the
 * @testing-library/react ``waitFor`` polling loop. Default
 * ``waitFor`` timeout (5 s) has plenty of headroom for the 250 ms
 * debounce.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, waitFor, fireEvent,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const getMock = vi.fn();
const postMock = vi.fn();
const patchMock = vi.fn();
const delMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    patch: (...a) => patchMock(...a),
    del: (...a) => delMock(...a),
  },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin", email: "a@x" } }),
  AuthProvider: ({ children }) => children,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {}, {
    success: vi.fn(), error: vi.fn(), info: vi.fn(),
  }),
}));


import { PriceBook } from "@/pages/ops/OpsHub";


const ITEMS = [
  { id: "i1", name: "Chlorine Tablets",  category: "Pool",        unit: "each" },
  { id: "i2", name: "Muriatic Acid",     category: "Pool",        unit: "gal" },
  { id: "i3", name: "Filter Cartridge",  category: "Pool",        unit: "each" },
  { id: "i4", name: "Mulch",             category: "Landscaping", unit: "yard" },
  { id: "i5", name: "Grass Seed",        category: "Landscaping", unit: "lb" },
  { id: "i6", name: "Labor",             category: "Common",      unit: "hr" },
];


function seedGetMock() {
  getMock.mockImplementation((path) => {
    if (path === "/items") return Promise.resolve(ITEMS);
    if (path === "/service-categories") return Promise.resolve([]);
    if (path === "/income-categories") return Promise.resolve([]);
    if (path === "/pricebook/suppliers") return Promise.resolve([]);
    return Promise.resolve([]);
  });
}


function mount() {
  return render(
    <MemoryRouter>
      <PriceBook />
    </MemoryRouter>,
  );
}


// Default waitFor timeout is 1000 ms; extend so the 250 ms debounce
// plus React commit cycles never race the polling loop.
const WAIT = { timeout: 3000 };


describe("PriceBook · client-side search field", () => {
  beforeEach(() => {
    getMock.mockReset(); postMock.mockReset();
    patchMock.mockReset(); delMock.mockReset();
    seedGetMock();
  });

  it("renders a search input with the correct testid + placeholder", async () => {
    mount();
    await waitFor(
      () => expect(screen.getByTestId(`pb-row-${ITEMS[0].id}`)).toBeInTheDocument(),
      WAIT,
    );
    const input = screen.getByTestId("pricebook-search-input");
    expect(input).toBeInTheDocument();
    expect(input.getAttribute("placeholder") || "")
      .toMatch(/search/i);
  });

  it("filters visible items on name substring (case-insensitive) after debounce", async () => {
    mount();
    await waitFor(
      () => expect(screen.getByTestId(`pb-row-${ITEMS[0].id}`)).toBeInTheDocument(),
      WAIT,
    );
    fireEvent.change(screen.getByTestId("pricebook-search-input"),
                       { target: { value: "filter" } });
    // Only "Filter Cartridge" (i3) survives.
    await waitFor(() => {
      expect(screen.getByTestId("pb-row-i3")).toBeInTheDocument();
      expect(screen.queryByTestId("pb-row-i1")).toBeNull();
      expect(screen.queryByTestId("pb-row-i4")).toBeNull();
    }, WAIT);
  });

  it("matches on category as a secondary field", async () => {
    mount();
    await waitFor(
      () => expect(screen.getByTestId(`pb-row-${ITEMS[0].id}`)).toBeInTheDocument(),
      WAIT,
    );
    fireEvent.change(screen.getByTestId("pricebook-search-input"),
                       { target: { value: "landscaping" } });
    await waitFor(() => {
      expect(screen.getByTestId("pb-row-i4")).toBeInTheDocument();
      expect(screen.getByTestId("pb-row-i5")).toBeInTheDocument();
      expect(screen.queryByTestId("pb-row-i1")).toBeNull();
    }, WAIT);
  });

  it("matches on unit as a tertiary field", async () => {
    mount();
    await waitFor(
      () => expect(screen.getByTestId(`pb-row-${ITEMS[0].id}`)).toBeInTheDocument(),
      WAIT,
    );
    fireEvent.change(screen.getByTestId("pricebook-search-input"),
                       { target: { value: "hr" } });
    await waitFor(() => {
      expect(screen.getByTestId("pb-row-i6")).toBeInTheDocument();
      expect(screen.queryByTestId("pb-row-i1")).toBeNull();
    }, WAIT);
  });

  it("renders empty state when no matches, with a Clear search button that restores the list", async () => {
    mount();
    await waitFor(
      () => expect(screen.getByTestId(`pb-row-${ITEMS[0].id}`)).toBeInTheDocument(),
      WAIT,
    );
    fireEvent.change(screen.getByTestId("pricebook-search-input"),
                       { target: { value: "zzz-nonexistent" } });
    const empty = await waitFor(
      () => screen.getByTestId("pricebook-search-empty"),
      WAIT,
    );
    expect(empty.textContent || "").toMatch(/zzz-nonexistent/);
    fireEvent.click(screen.getByTestId("pricebook-search-clear"));
    await waitFor(() => {
      expect(screen.getByTestId("pb-row-i1")).toBeInTheDocument();
      expect(screen.getByTestId("pb-row-i4")).toBeInTheDocument();
    }, WAIT);
  });

  it("clearing the input via typing restores the full list", async () => {
    mount();
    await waitFor(
      () => expect(screen.getByTestId(`pb-row-${ITEMS[0].id}`)).toBeInTheDocument(),
      WAIT,
    );
    fireEvent.change(screen.getByTestId("pricebook-search-input"),
                       { target: { value: "filter" } });
    await waitFor(() =>
      expect(screen.queryByTestId("pb-row-i1")).toBeNull(),
      WAIT,
    );
    fireEvent.change(screen.getByTestId("pricebook-search-input"),
                       { target: { value: "" } });
    await waitFor(() => {
      expect(screen.getByTestId("pb-row-i1")).toBeInTheDocument();
      expect(screen.getByTestId("pb-row-i4")).toBeInTheDocument();
    }, WAIT);
  });
});
