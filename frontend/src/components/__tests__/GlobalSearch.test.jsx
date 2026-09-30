/**
 * Phase GLOBAL-SEARCH-UNIFY · Feb-2026 — ⌘K palette tests.
 *
 * Locks:
 *   1. ``⌘K`` opens the palette on mac; ``Ctrl+K`` opens on non-mac.
 *   2. ``Escape`` closes it (and drops focus back to the pre-open
 *      element).
 *   3. Input auto-focuses on open.
 *   4. Focus returns to the previously-focused element on close.
 *   5. Typing filters results (test with a mocked backend).
 *   6. Selecting a result navigates via ``useNavigate``.
 *   7. Palette surface is solid white with black text; the keyboard-
 *      highlighted row uses a contrasting light-gray background.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";


const { navigateSpy, searchGlobalSpy, apiGetSpy } = vi.hoisted(() => ({
  navigateSpy: vi.fn(),
  searchGlobalSpy: vi.fn(),
  apiGetSpy: vi.fn(),
}));


vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateSpy,
}));

// Legacy searchGlobal client — retained as a no-op stub so any
// transitive import still resolves.  ``<GlobalSearch>`` no longer
// consumes it (migrated to ``useGlobalSearchResults`` on
// ``/api/search`` in Feb-2026), but the mock keeps the file
// importable across other test suites.
vi.mock("@/lib/globalSearchClient", () => ({
  searchGlobal: (...a) => searchGlobalSpy(...a),
}));

// Feb-2026 · Restore visible universal search — the palette now
// consumes ``useGlobalSearchResults`` which hits ``GET /api/search``
// via the shared ``@/api`` wrapper.  Mock the wrapper so the
// dropdown backend rows arrive without a real network call.
vi.mock("@/api", () => ({ api: { get: (...a) => apiGetSpy(...a) } }));

// The nav-index search is synchronous — mock it with a static
// catalog that includes an "Invoices" entry so page-kind results
// exercise the same commit path a customer/document result uses.
vi.mock("@/lib/navIndex", () => ({
  searchNavIndex: (q) => {
    const cat = [
      { title: "Invoices",  path: "/invoices" },
      { title: "Customers", path: "/customers" },
      { title: "Jobs",      path: "/jobs" },
    ];
    const needle = (q || "").toLowerCase();
    return needle
      ? cat.filter((r) => r.title.toLowerCase().includes(needle))
      : [];
  },
}));


import GlobalSearch from "@/components/GlobalSearch";


beforeEach(() => {
  navigateSpy.mockReset();
  searchGlobalSpy.mockReset();
  searchGlobalSpy.mockResolvedValue({ customers: [], documents: [] });
  apiGetSpy.mockReset();
  apiGetSpy.mockResolvedValue({
    customers: [], jobs: [], invoices: [], quotes: [], leads: [],
  });
});

afterEach(() => {
  vi.useRealTimers();
});


function _mount() {
  return render(<GlobalSearch />);
}


describe("<GlobalSearch /> — open + close via keyboard", () => {
  it("Ctrl+K (non-mac) opens the palette", () => {
    _mount();
    expect(screen.queryByTestId("global-search-overlay")).toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByTestId("global-search-overlay")).toBeTruthy();
  });

  it("Cmd+K (metaKey) opens the palette on mac", () => {
    // Force navigator.userAgent to look like macOS for the isMac
    // detection. GlobalSearch's kbd-hint reads the ua on mount.
    const origUA = Object.getOwnPropertyDescriptor(
      window.navigator, "userAgent",
    );
    Object.defineProperty(window.navigator, "userAgent", {
      value: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
      configurable: true,
    });
    try {
      _mount();
      fireEvent.keyDown(window, { key: "k", metaKey: true });
      expect(screen.getByTestId("global-search-overlay")).toBeTruthy();
      // Mac hint reads ⌘K (U+2318 + K), not "Ctrl+K".
      expect(
        screen.getByTestId("global-search-kbd-hint").textContent,
      ).toBe("\u2318K");
    } finally {
      if (origUA) {
        Object.defineProperty(window.navigator, "userAgent", origUA);
      }
    }
  });

  it("Escape closes the palette", async () => {
    _mount();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await waitFor(() =>
      screen.getByTestId("global-search-input"),
    );
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByTestId("global-search-overlay")).toBeNull(),
    );
  });

  it("click-outside on the scrim closes the palette", async () => {
    _mount();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const overlay = screen.getByTestId("global-search-overlay");
    fireEvent.mouseDown(overlay, {
      // simulate a mousedown ON the overlay itself (not the panel).
      target: overlay, currentTarget: overlay,
    });
    await waitFor(() =>
      expect(screen.queryByTestId("global-search-overlay")).toBeNull(),
    );
  });
});


describe("<GlobalSearch /> — focus management", () => {
  it("input auto-focuses on open", async () => {
    _mount();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await waitFor(() =>
      screen.getByTestId("global-search-input"),
    );
    await waitFor(() =>
      expect(document.activeElement).toBe(input),
    );
  });

  it("focus returns to the previously-focused element on close",
    async () => {
      // Mount an external focusable + the palette.
      const external = document.createElement("button");
      external.setAttribute("data-testid", "external-btn");
      external.textContent = "Focus me first";
      document.body.appendChild(external);
      external.focus();
      expect(document.activeElement).toBe(external);
      _mount();
      // Open + focus the palette.
      fireEvent.keyDown(window, { key: "k", ctrlKey: true });
      const input = await waitFor(() =>
        screen.getByTestId("global-search-input"),
      );
      await waitFor(() => expect(document.activeElement).toBe(input));
      // Close via Escape — focus must snap back to ``external``.
      fireEvent.keyDown(input, { key: "Escape" });
      await waitFor(() => expect(document.activeElement).toBe(external));
      document.body.removeChild(external);
    });
});


describe("<GlobalSearch /> — result surfacing + commit", () => {
  it("typing filters the local Pages section synchronously", async () => {
    _mount();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await waitFor(() =>
      screen.getByTestId("global-search-input"),
    );
    fireEvent.change(input, { target: { value: "inv" } });
    // Page row for "Invoices" surfaces immediately.
    await waitFor(() => {
      const rows = screen.getAllByRole("option");
      expect(rows.some((el) => el.textContent.includes("Invoices"))).toBe(true);
    });
  });

  it("Enter on a highlighted row commits + navigates", async () => {
    _mount();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await waitFor(() =>
      screen.getByTestId("global-search-input"),
    );
    fireEvent.change(input, { target: { value: "inv" } });
    // First row is highlighted by default (see ``setHighlight(0)``
    // reset on query change).
    await waitFor(() =>
      expect(screen.queryByTestId("global-search-result-0")).toBeTruthy(),
    );
    fireEvent.keyDown(input, { key: "Enter" });
    expect(navigateSpy).toHaveBeenCalledWith("/invoices");
    // Palette closes on commit.
    await waitFor(() =>
      expect(screen.queryByTestId("global-search-overlay")).toBeNull(),
    );
  });

  it("clicking a document result navigates to /invoices/<id>", async () => {
    // Feb-2026 · Restore visible universal search — the palette
    // now consumes ``useGlobalSearchResults`` which hits
    // ``GET /api/search`` and merges ``jobs + invoices + quotes``
    // into the palette's ``documents`` bucket with a per-row
    // ``kind`` tag.  The response shape is the unified
    // ``{id, primary, secondary}`` triplet, not the legacy
    // ``{type, display_id, title}`` shape.
    apiGetSpy.mockResolvedValue({
      customers: [],
      jobs: [],
      invoices: [
        { id: "inv-42", primary: "Invoice INV-42",
          secondary: "Someone · $100.00" },
      ],
      quotes: [], leads: [],
    });
    _mount();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await waitFor(() =>
      screen.getByTestId("global-search-input"),
    );
    fireEvent.change(input, { target: { value: "pool" } });
    // Real 300ms debounce inside ``useGlobalSearchResults``; give
    // it enough real time to fire, resolve, and re-render.
    const row = await waitFor(() => {
      const candidate = screen.queryAllByRole("option").find(
        (el) => el.getAttribute("data-kind") === "document",
      );
      if (!candidate) throw new Error("document row not yet rendered");
      return candidate;
    }, { timeout: 2500 });
    fireEvent.mouseDown(row);
    expect(navigateSpy).toHaveBeenCalledWith("/invoices/inv-42");
  });
});


describe("<GlobalSearch /> — solid white / black text styling", () => {
  it("panel surface is solid #FFFFFF with #000000 text", async () => {
    _mount();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const panel = await waitFor(() =>
      screen.getByTestId("global-search-panel"),
    );
    expect(panel.style.backgroundColor).toBe("rgb(255, 255, 255)");
    expect(panel.style.color).toBe("rgb(0, 0, 0)");
  });

  it("highlighted result row uses a light-gray contrast bg (#EEEEEE)",
    async () => {
      _mount();
      fireEvent.keyDown(window, { key: "k", ctrlKey: true });
      const input = await waitFor(() =>
        screen.getByTestId("global-search-input"),
      );
      fireEvent.change(input, { target: { value: "inv" } });
      const row = await waitFor(() =>
        screen.getByTestId("global-search-result-0"),
      );
      expect(row.getAttribute("data-active")).toBe("true");
      expect(row.style.backgroundColor).toBe("rgb(238, 238, 238)");
    });
});
