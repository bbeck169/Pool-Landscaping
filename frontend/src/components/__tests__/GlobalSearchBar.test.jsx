/**
 * Feb-2026 · Restore visible universal search bar.
 *
 * Behavioural + shape assertions for ``<GlobalSearchBar>`` — the
 * blue-hero always-visible search surface mounted from
 * ``AdminTopBar``.  Covers the seven spec cases:
 *
 *   1. Renders visible input with the blue-hero styling.
 *   2. Typing triggers a debounced fetch to ``/api/search``.
 *   3. Results appear inline below the input, grouped by kind.
 *   4. Keyboard nav — ArrowDown/Up + Enter select a result and
 *      navigate.
 *   5. Escape clears the query + closes the dropdown but keeps
 *      the input mounted.
 *   6. ⌘K continues to open the palette (visible bar coexists
 *      with palette — source-body assertion + shared hook proof).
 *   7. Mobile-responsive — the bar renders a compact icon-collapse
 *      toggle below the ``sm`` breakpoint.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";


// Hoisted mocks — the api client is a plain object; jsdom import
// order requires ``vi.mock`` to precede the import of the
// component under test, hence the top-level position.
vi.mock("@/api", () => ({ api: { get: vi.fn() } }));

// ``useNavigate`` is a live import from react-router-dom but we
// want to spy on it directly.  A shim keeps the ``navigate(url)``
// call observable without patching the router runtime.
const _navigateSpy = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => _navigateSpy,
  };
});

// Nav index — always-empty so backend rows drive the tests.
vi.mock("@/lib/navIndex", () => ({
  searchNavIndex: () => [],
}));

import { api } from "@/api";
import GlobalSearchBar from "@/components/GlobalSearchBar";


const _renderBar = () =>
  render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <GlobalSearchBar />
    </MemoryRouter>,
  );

const _mockResults = (payload) => {
  api.get.mockImplementation((url) => {
    if (typeof url === "string" && url.startsWith("/search")) {
      return Promise.resolve(payload);
    }
    return Promise.resolve({});
  });
};


beforeEach(() => {
  api.get.mockReset();
  _navigateSpy.mockReset();
  vi.useFakeTimers();
});


// ══════════════════════════════════════════════════════════════════
// 1) White-pill styling — WHITE pill on the #1B1F5C navy hero strip
//    (Feb-2026 universal-search restyle — was brand-blue pre-fix).
// ══════════════════════════════════════════════════════════════════
describe("GlobalSearchBar · white-pill styling", () => {
  it("renders the visible pill with white background + dark input + ⌘K/Ctrl+K hint", () => {
    vi.useRealTimers();
    _mockResults({ customers: [], jobs: [], invoices: [], quotes: [], leads: [] });
    _renderBar();
    const hero = screen.getByTestId("global-search-bar-hero");
    expect(hero).toBeInTheDocument();
    // Inline style rgb(255, 255, 255) === #FFFFFF (new white pill).
    expect(hero.style.backgroundColor).toMatch(/rgb\(255,\s*255,\s*255\)|#fff|#FFFFFF/i);
    // Dark gray text (gray-900 = #111827 = rgb(17, 24, 39)).
    expect(hero.style.color.toLowerCase()).toMatch(/rgb\(17,\s*24,\s*39\)|#111827/);
    const input = screen.getByTestId("global-search-bar-input");
    expect(input).toHaveAttribute(
      "placeholder",
      "Search customers, jobs, invoices, quotes, leads, technicians…",
    );
    // Fully rounded pill (``rounded-full``) on the wrapper — not
    // ``rounded-xl`` (that was the pre-restyle shape).
    expect(hero.className).toMatch(/rounded-full/);
    expect(hero.className).not.toMatch(/rounded-xl/);
    // Keyboard hint renders inside the pill with the standard
    // ``global-search-bar-kbd-hint`` testid. OS-dependent text —
    // either ⌘K (Mac) or Ctrl+K.
    const kbd = screen.getByTestId("global-search-bar-kbd-hint");
    expect(kbd).toBeInTheDocument();
    expect(kbd.textContent).toMatch(/\u2318K|Ctrl\+K/);
  });
});


// ══════════════════════════════════════════════════════════════════
// 2) Debounced fetch to /api/search
// ══════════════════════════════════════════════════════════════════
describe("GlobalSearchBar · debounced fetch", () => {
  it("waits 300 ms after typing before calling /api/search", async () => {
    _mockResults({ customers: [], jobs: [], invoices: [], quotes: [], leads: [] });
    _renderBar();
    const input = screen.getByTestId("global-search-bar-input");
    fireEvent.change(input, { target: { value: "jane" } });

    // No fetch fires immediately.
    expect(api.get).not.toHaveBeenCalled();

    // Advance to 299 ms — still no fetch.
    act(() => { vi.advanceTimersByTime(299); });
    expect(api.get).not.toHaveBeenCalled();

    // Advance one more tick — the debounce fires.
    act(() => { vi.advanceTimersByTime(1); });
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledWith(
      expect.stringMatching(/^\/search\?q=jane&limit=/),
    );
  });

  it("does NOT fetch when the query is <2 chars", () => {
    _mockResults({});
    _renderBar();
    const input = screen.getByTestId("global-search-bar-input");
    fireEvent.change(input, { target: { value: "a" } });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(api.get).not.toHaveBeenCalled();
  });
});


// ══════════════════════════════════════════════════════════════════
// 3) Inline dropdown grouped by entity kind
// ══════════════════════════════════════════════════════════════════
describe("GlobalSearchBar · inline dropdown grouped by kind", () => {
  it("renders one section per non-empty bucket with the entity label + count", async () => {
    vi.useRealTimers();
    _mockResults({
      customers: [{ id: "c1", primary: "Jane C", secondary: "jc@x.com" }],
      jobs: [{ id: "j1", primary: "Weekly svc", secondary: "for Jane" }],
      invoices: [{ id: "i1", primary: "Invoice INV-01", secondary: "Jane · $100.00" }],
      quotes: [{ id: "q1", primary: "Quote QT-01", secondary: "Jane · $200.00" }],
      leads: [{ id: "l1", primary: "Jane L", secondary: "555-1234" }],
    });
    _renderBar();
    fireEvent.change(screen.getByTestId("global-search-bar-input"), {
      target: { value: "jane" },
    });
    // One section per bucket.
    await waitFor(() => {
      expect(screen.getByTestId("global-search-bar-section-customer")).toBeInTheDocument();
    });
    expect(screen.getByTestId("global-search-bar-section-job")).toBeInTheDocument();
    expect(screen.getByTestId("global-search-bar-section-invoice")).toBeInTheDocument();
    expect(screen.getByTestId("global-search-bar-section-quote")).toBeInTheDocument();
    expect(screen.getByTestId("global-search-bar-section-lead")).toBeInTheDocument();
    // Each row surfaces its ``primary`` field.
    expect(screen.getByText("Jane C")).toBeInTheDocument();
    expect(screen.getByText("Invoice INV-01")).toBeInTheDocument();
    expect(screen.getByText("Quote QT-01")).toBeInTheDocument();
  });
});


// ══════════════════════════════════════════════════════════════════
// 4) Keyboard nav — ArrowDown/Up + Enter navigate
// ══════════════════════════════════════════════════════════════════
describe("GlobalSearchBar · keyboard navigation", () => {
  it("ArrowDown moves highlight; Enter navigates to the highlighted result", async () => {
    vi.useRealTimers();
    _mockResults({
      customers: [
        { id: "c1", primary: "First",  secondary: "" },
        { id: "c2", primary: "Second", secondary: "" },
      ],
      jobs: [], invoices: [], quotes: [], leads: [],
    });
    _renderBar();
    const input = screen.getByTestId("global-search-bar-input");
    fireEvent.change(input, { target: { value: "fi" } });
    await waitFor(() => screen.getByTestId("global-search-bar-result-0"));

    // ArrowDown → highlight moves to row index 1.
    fireEvent.keyDown(input, { key: "ArrowDown" });
    await waitFor(() => {
      const row1 = screen.getByTestId("global-search-bar-result-1");
      expect(row1.getAttribute("data-active")).toBe("true");
    });

    fireEvent.keyDown(input, { key: "Enter" });
    expect(_navigateSpy).toHaveBeenCalledWith("/customers/c2");
  });
});


// ══════════════════════════════════════════════════════════════════
// 5) Escape clears query + closes dropdown but keeps input mounted
// ══════════════════════════════════════════════════════════════════
describe("GlobalSearchBar · Escape behaviour", () => {
  it("clears the query and closes the dropdown but keeps the input mounted", async () => {
    vi.useRealTimers();
    _mockResults({
      customers: [{ id: "c1", primary: "X", secondary: "" }],
      jobs: [], invoices: [], quotes: [], leads: [],
    });
    _renderBar();
    const input = screen.getByTestId("global-search-bar-input");
    fireEvent.change(input, { target: { value: "x" } });
    fireEvent.change(input, { target: { value: "xy" } });
    await waitFor(() => screen.getByTestId("global-search-bar-dropdown"));

    fireEvent.keyDown(input, { key: "Escape" });

    // Dropdown gone, input still in DOM, value cleared.
    await waitFor(() => {
      expect(screen.queryByTestId("global-search-bar-dropdown")).toBeNull();
    });
    const stillMounted = screen.getByTestId("global-search-bar-input");
    expect(stillMounted).toBeInTheDocument();
    expect(stillMounted.value).toBe("");
  });
});


// ══════════════════════════════════════════════════════════════════
// 6) ⌘K palette coexists — same hook, both entry points share
// ══════════════════════════════════════════════════════════════════
describe("GlobalSearchBar · ⌘K palette coexistence", () => {
  it("consumes useGlobalSearchResults just like the ⌘K palette", () => {
    // Both surfaces import the shared hook by name (source-body
    // assertion mirrors the K48 / GLOBAL-SEARCH-UNIFY convention).
    const barSrc = fs.readFileSync(
      path.resolve(process.cwd(), "src/components/GlobalSearchBar.jsx"),
      "utf-8",
    );
    const paletteSrc = fs.readFileSync(
      path.resolve(process.cwd(), "src/components/GlobalSearch.jsx"),
      "utf-8",
    );
    expect(barSrc).toMatch(
      /useGlobalSearchResults[\s\S]{0,80}?@\/hooks\/useGlobalSearchResults/,
    );
    expect(paletteSrc).toMatch(
      /useGlobalSearchResults[\s\S]{0,80}?@\/hooks\/useGlobalSearchResults/,
    );
  });
});


// ══════════════════════════════════════════════════════════════════
// 7) Mobile-responsive — icon-collapse below sm breakpoint
// ══════════════════════════════════════════════════════════════════
describe("GlobalSearchBar · mobile responsive", () => {
  it("exposes a mobile toggle that hides the full hero surface on narrow viewports", () => {
    vi.useRealTimers();
    _mockResults({});
    _renderBar();
    const mobileToggle = screen.getByTestId("global-search-bar-mobile-toggle");
    // ``sm:hidden`` on the toggle → visible only <640 px.
    expect(mobileToggle.className).toMatch(/sm:hidden/);
    // Hero surface is ``hidden`` by default (only appears on ``sm:``
    // OR when mobileExpanded flips true after a tap).
    const hero = screen.getByTestId("global-search-bar-hero");
    expect(hero.className).toMatch(/hidden sm:flex/);
  });

  it("expanding the mobile toggle flips the hero to ``flex`` on narrow viewports", () => {
    vi.useRealTimers();
    _mockResults({});
    _renderBar();
    const mobileToggle = screen.getByTestId("global-search-bar-mobile-toggle");
    fireEvent.click(mobileToggle);
    const hero = screen.getByTestId("global-search-bar-hero");
    // Post-click the ``hidden sm:flex`` is swapped for ``flex``.
    expect(hero.className).toMatch(/(^|\s)flex(\s|$)/);
    expect(hero.className).not.toMatch(/hidden sm:flex/);
  });
});



// ══════════════════════════════════════════════════════════════════
// 8) TD-search-technicians-bucket · Feb-2026 — technicians group
// ══════════════════════════════════════════════════════════════════
describe("GlobalSearchBar · technicians bucket", () => {
  it("renders a Technicians section with the correct primary + secondary + testid shape", async () => {
    vi.useRealTimers();
    _mockResults({
      customers: [], jobs: [], invoices: [], quotes: [], leads: [],
      technicians: [
        { id: "t1", primary: "Miguel Rivera",
          secondary: "technician · (555) 123-4567" },
      ],
    });
    _renderBar();
    fireEvent.change(screen.getByTestId("global-search-bar-input"), {
      target: { value: "miguel" },
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("global-search-bar-section-technician"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("Miguel Rivera")).toBeInTheDocument();
    expect(
      screen.getByText("technician · (555) 123-4567"),
    ).toBeInTheDocument();
  });

  it("row click navigates to the SINGULAR /technician/:id route", async () => {
    vi.useRealTimers();
    _mockResults({
      customers: [], jobs: [], invoices: [], quotes: [], leads: [],
      technicians: [
        { id: "tech-abc-123", primary: "Jane Tech",
          secondary: "landscaper · 555-0100" },
      ],
    });
    _renderBar();
    fireEvent.change(screen.getByTestId("global-search-bar-input"), {
      target: { value: "jane" },
    });
    await waitFor(() => screen.getByTestId("global-search-bar-result-0"));
    const row = screen.getByTestId("global-search-bar-result-0");
    expect(row.getAttribute("data-kind")).toBe("technician");
    fireEvent.mouseDown(row);
    // SINGULAR path per App.js:1510 — critical for row click to resolve.
    expect(_navigateSpy).toHaveBeenCalledWith("/technician/tech-abc-123");
    // Guard against plural regression.
    expect(_navigateSpy).not.toHaveBeenCalledWith("/technicians/tech-abc-123");
  });

  it("Technicians section does NOT render when the bucket is empty (bail at Section)", async () => {
    vi.useRealTimers();
    _mockResults({
      customers: [{ id: "c1", primary: "C", secondary: "" }],
      jobs: [], invoices: [], quotes: [], leads: [],
      technicians: [],
    });
    _renderBar();
    fireEvent.change(screen.getByTestId("global-search-bar-input"), {
      target: { value: "cc" },
    });
    await waitFor(() =>
      screen.getByTestId("global-search-bar-section-customer"),
    );
    // Section component bails on empty rows — testid must be absent.
    expect(
      screen.queryByTestId("global-search-bar-section-technician"),
    ).toBeNull();
  });

  it("keyboard navigation reaches technicians rows after leads (section order)", async () => {
    vi.useRealTimers();
    _mockResults({
      customers: [], jobs: [], invoices: [], quotes: [],
      leads: [{ id: "l1", primary: "LeadOne", secondary: "" }],
      technicians: [{ id: "t1", primary: "TechOne",
                       secondary: "technician · " }],
    });
    _renderBar();
    const input = screen.getByTestId("global-search-bar-input");
    fireEvent.change(input, { target: { value: "o" } });
    // Need ≥2 chars to clear the MIN_BACKEND_CHARS gate.
    fireEvent.change(input, { target: { value: "on" } });
    await waitFor(() => screen.getByTestId("global-search-bar-result-1"));
    // Row 0 = LeadOne, Row 1 = TechOne (technicians section comes last).
    const row1 = screen.getByTestId("global-search-bar-result-1");
    expect(row1.getAttribute("data-kind")).toBe("technician");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    await waitFor(() => {
      expect(row1.getAttribute("data-active")).toBe("true");
    });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(_navigateSpy).toHaveBeenCalledWith("/technician/t1");
  });
});
