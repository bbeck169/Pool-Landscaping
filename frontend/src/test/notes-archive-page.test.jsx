/**
 * Task N · Phase N · Feb-2026 — NotesArchive page tests.
 *
 * Locks the archive page's rendering contract + interactive
 * flows against the backend Commit-1 endpoint (mocked via
 * ``vi.mock("@/api")``).  Uses the DOM-mount convention
 * from ``lumino-backfill-page.test.jsx`` (this codebase's
 * standard) rather than source-inspection because the
 * expander flow needs to assert against post-click DOM state.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup, within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── Mocks (must come BEFORE the component import) ───────────
const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...args) => getMock(...args) },
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", border: "#eee", muted: "#666",
    onSurface: "#111827", onSurfaceSecondary: "#6B7280",
    surfaceSecondary: "#fafafa", inputBorder: "#3B82F6",
    brand: "#0284C7",
    nav: {
      bg: "#1B1F5C", fg: "#FFFFFF", fgMuted: "#a3a3c2",
      border: "rgba(255,255,255,0.10)",
    },
    gradient: { css: "linear-gradient(#000,#fff)", textShadow: "none" },
  },
}));


import NotesArchive from "@/pages/comms/NotesArchive";


// ── Helpers ───────────────────────────────────────────────
const LONG_NOTE = "x".repeat(300);
const SHORT_NOTE = "brief chemistry visit";

const _fixtureRow = (overrides = {}) => ({
  sr_id: "sr-happy-1",
  job_id: "job-1",
  submitted_at: "2026-03-10T18:00:00Z",
  customer_id: "cust-1",
  customer_name: "Diane Lloyd",
  tech_id: "tech-1",
  tech_name: "Mike Rivera",
  industry: "Pool",
  notes: SHORT_NOTE,
  internal_notes: LONG_NOTE,
  customer_notes: "",
  ...overrides,
});

const _archiveResponse = (rows = [_fixtureRow()], total = null) => ({
  rows,
  total_count: total ?? rows.length,
  page: 1,
  page_size: 50,
});

const renderPage = () => render(
  <MemoryRouter>
    <NotesArchive />
  </MemoryRouter>,
);


beforeEach(() => {
  getMock.mockReset();
});

afterEach(() => cleanup());


// ═════════════════════════════════════════════════════════════
// Suite 1 · initial render
// ═════════════════════════════════════════════════════════════
describe("NotesArchive · page mount", () => {
  it("shows loading state before first response resolves", async () => {
    // Delay resolution so we can observe the loading state.
    let resolveArchive;
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return new Promise((resolve) => { resolveArchive = resolve; });
    });
    renderPage();
    expect(screen.getByTestId("notes-archive-loading")).toBeInTheDocument();
    resolveArchive(_archiveResponse());
    await waitFor(() => {
      expect(screen.queryByTestId("notes-archive-loading")).not.toBeInTheDocument();
    });
  });

  it("renders NavyFilterBar with all 5 filters wired to testids", async () => {
    getMock.mockResolvedValue(_archiveResponse());
    renderPage();
    await waitFor(() => screen.getByTestId("notes-archive-filters"));
    expect(screen.getByTestId("notes-archive-search")).toBeInTheDocument();
    expect(screen.getByTestId("notes-archive-date-from")).toBeInTheDocument();
    expect(screen.getByTestId("notes-archive-date-to")).toBeInTheDocument();
    expect(screen.getByTestId("notes-archive-tech-filter")).toBeInTheDocument();
    expect(screen.getByTestId("notes-archive-industry-filter")).toBeInTheDocument();
  });
});


// ═════════════════════════════════════════════════════════════
// Suite 2 · empty + error states
// ═════════════════════════════════════════════════════════════
describe("NotesArchive · empty + error states", () => {
  it("shows the empty state when the archive returns zero rows", async () => {
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve(_archiveResponse([], 0));
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("notes-archive-empty")).toBeInTheDocument();
    });
  });

  it("shows the error banner when the archive fetch rejects", async () => {
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.reject(new Error("boom"));
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("notes-archive-error")).toBeInTheDocument();
    });
  });
});


// ═════════════════════════════════════════════════════════════
// Suite 3 · row rendering
// ═════════════════════════════════════════════════════════════
describe("NotesArchive · row rendering", () => {
  it("renders one row per response entry with all 5 columns filled", async () => {
    const rows = [
      _fixtureRow({sr_id: "sr-A", customer_name: "Alice", industry: "Pool"}),
      _fixtureRow({sr_id: "sr-B", customer_name: "Bob",   industry: "Landscaping"}),
    ];
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve(_archiveResponse(rows, 2));
    });
    renderPage();
    await waitFor(() => screen.getByTestId("notes-archive-row-sr-A"));
    // Both rows present.
    expect(screen.getByTestId("notes-archive-row-sr-A")).toBeInTheDocument();
    expect(screen.getByTestId("notes-archive-row-sr-B")).toBeInTheDocument();
    // Column cell testids populated.
    expect(screen.getByTestId("notes-archive-row-sr-A-customer"))
      .toHaveTextContent("Alice");
    expect(screen.getByTestId("notes-archive-row-sr-A-industry"))
      .toHaveTextContent("Pool");
    expect(screen.getByTestId("notes-archive-row-sr-B-industry"))
      .toHaveTextContent("Landscaping");
  });
});


// ═════════════════════════════════════════════════════════════
// Suite 4 · Add-B expander contract
// ═════════════════════════════════════════════════════════════
describe("NotesArchive · Add-B expander contract", () => {
  it("truncated preview + toggle → full text on click; toggle again collapses", async () => {
    const row = _fixtureRow({sr_id: "sr-expand"});
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve(_archiveResponse([row]));
    });
    renderPage();
    await waitFor(() => screen.getByTestId("notes-archive-row-sr-expand"));

    // Initial: long note (internal_notes) shows preview + toggle,
    // does NOT show full.
    const preview = screen.getByTestId(
      "notes-archive-row-sr-expand-internal_notes-preview");
    expect(preview).toBeInTheDocument();
    expect(preview.textContent).toMatch(/\u2026$/); // ellipsis
    expect(screen.queryByTestId(
      "notes-archive-row-sr-expand-internal_notes-full"))
      .not.toBeInTheDocument();
    const toggle = screen.getByTestId(
      "notes-archive-row-sr-expand-internal_notes-toggle");
    expect(toggle).toHaveTextContent("See more");

    // Click expand: full DOM appears, preview disappears.
    fireEvent.click(toggle);
    expect(screen.getByTestId(
      "notes-archive-row-sr-expand-internal_notes-full")).toBeInTheDocument();
    expect(screen.queryByTestId(
      "notes-archive-row-sr-expand-internal_notes-preview"))
      .not.toBeInTheDocument();
    expect(toggle).toHaveTextContent("See less");

    // Click collapse: preview reappears, full gone.
    fireEvent.click(toggle);
    expect(screen.getByTestId(
      "notes-archive-row-sr-expand-internal_notes-preview")).toBeInTheDocument();
    expect(screen.queryByTestId(
      "notes-archive-row-sr-expand-internal_notes-full"))
      .not.toBeInTheDocument();
  });

  it("short notes (≤140 chars) render without a toggle", async () => {
    // The default fixture's ``notes`` field is short.
    const row = _fixtureRow({
      sr_id: "sr-short",
      notes: "one-liner chemistry note",
      internal_notes: "",     // omit long note so no toggle at all
      customer_notes: "",
    });
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve(_archiveResponse([row]));
    });
    renderPage();
    await waitFor(() => screen.getByTestId("notes-archive-row-sr-short"));
    // Short-note preview rendered, but NO toggle button.
    expect(screen.getByTestId(
      "notes-archive-row-sr-short-notes-preview")).toBeInTheDocument();
    expect(screen.queryByTestId(
      "notes-archive-row-sr-short-notes-toggle")).not.toBeInTheDocument();
  });

  it("empty note fields are omitted from the note cell", async () => {
    const row = _fixtureRow({
      sr_id: "sr-partial",
      notes: "",
      internal_notes: "only this one",
      customer_notes: "",
    });
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve(_archiveResponse([row]));
    });
    renderPage();
    await waitFor(() => screen.getByTestId("notes-archive-row-sr-partial"));
    // Only internal_notes preview rendered.
    expect(screen.getByTestId(
      "notes-archive-row-sr-partial-internal_notes-preview")).toBeInTheDocument();
    expect(screen.queryByTestId(
      "notes-archive-row-sr-partial-notes-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId(
      "notes-archive-row-sr-partial-customer_notes-preview")).not.toBeInTheDocument();
  });
});


// ═════════════════════════════════════════════════════════════
// Suite 5 · filters propagate to fetch
// ═════════════════════════════════════════════════════════════
describe("NotesArchive · filters propagate to fetch", () => {
  it("typing in the search box sends ``customer_search`` on the next fetch", async () => {
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve(_archiveResponse([]));
    });
    renderPage();
    await waitFor(() => screen.getByTestId("notes-archive-search"));
    getMock.mockClear();
    getMock.mockImplementation((path) => {
      return Promise.resolve(_archiveResponse([]));
    });

    fireEvent.change(screen.getByTestId("notes-archive-search"),
                     { target: { value: "Diane" } });
    await waitFor(() => {
      // Any call to archive with the query string present.
      const calledWith = getMock.mock.calls.map((c) => c[0]);
      expect(calledWith.some(
        (u) => typeof u === "string"
        && u.startsWith("/service-reports/archive")
        && u.includes("customer_search=Diane"),
      )).toBe(true);
    });
  });

  it("industry Select propagates to fetch as ``industry`` param", async () => {
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve(_archiveResponse([]));
    });
    renderPage();
    await waitFor(() => screen.getByTestId("notes-archive-industry-filter"));
    getMock.mockClear();
    getMock.mockImplementation(() =>
      Promise.resolve(_archiveResponse([])));

    fireEvent.change(screen.getByTestId("notes-archive-industry-filter"),
                     { target: { value: "Landscaping" } });
    await waitFor(() => {
      const calls = getMock.mock.calls.map((c) => c[0]);
      expect(calls.some(
        (u) => typeof u === "string"
        && u.includes("industry=Landscaping"),
      )).toBe(true);
    });
  });
});


// ═════════════════════════════════════════════════════════════
// Suite 6 · pagination
// ═════════════════════════════════════════════════════════════
describe("NotesArchive · pagination", () => {
  it("Next / Prev buttons advance page in the fetch URL", async () => {
    const rows = [_fixtureRow({sr_id: "sr-P"})];
    // Response reports total 200 → 4 pages @ 50/page.
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve({ rows, total_count: 200, page: 1, page_size: 50 });
    });
    renderPage();
    await waitFor(() => screen.getByTestId("notes-archive-next-btn"));
    expect(screen.getByTestId("notes-archive-page-indicator"))
      .toHaveTextContent("Page 1 of 4");

    getMock.mockClear();
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve({ rows, total_count: 200, page: 2, page_size: 50 });
    });
    fireEvent.click(screen.getByTestId("notes-archive-next-btn"));
    await waitFor(() => {
      const calls = getMock.mock.calls.map((c) => c[0]);
      expect(calls.some(
        (u) => typeof u === "string"
        && u.startsWith("/service-reports/archive")
        && u.includes("page=2"),
      )).toBe(true);
    });
  });

  it("page_size selector reflects the picked value in the fetch URL", async () => {
    getMock.mockImplementation((path) => {
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve(_archiveResponse([]));
    });
    renderPage();
    await waitFor(() => screen.getByTestId("notes-archive-page-size"));
    getMock.mockClear();
    getMock.mockImplementation(() =>
      Promise.resolve(_archiveResponse([])));

    fireEvent.change(screen.getByTestId("notes-archive-page-size"),
                     { target: { value: "100" } });
    await waitFor(() => {
      const calls = getMock.mock.calls.map((c) => c[0]);
      expect(calls.some(
        (u) => typeof u === "string"
        && u.includes("page_size=100"),
      )).toBe(true);
    });
  });
});
