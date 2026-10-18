/**
 * TD-75 · Feb-2026 — Portal Service Reports LIST acceptance locks.
 *
 * Coverage:
 *   1. Free-text search input is REMOVED from
 *      `pages/portal/PortalServiceReports.jsx` (source-grep + DOM
 *      negative lock).
 *   2. All search-related local state / debounce / query-param
 *      wiring is removed.
 *   3. Instructional hint ("Click any visit below to open its full
 *      details, photos, and chemicals.") paints with Tailwind
 *      `text-gray-700` (#374151) — operator-ruled darker-grey
 *      legibility bump — and no longer resolves `colors.muted`.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/portal/PortalServiceReports.jsx"),
  "utf-8",
);

// ────────────────────────────────────────────────────────────────
// 1. Source-grep locks — the LIST surface no longer wires search.
// ────────────────────────────────────────────────────────────────
describe("TD-75 · source-level removal of the free-text search input", () => {
  it("no `<input type=\"search\">` tag remains in the file", () => {
    expect(SRC).not.toMatch(/type="search"/);
  });

  it("no `Search notes, name, address` placeholder string remains", () => {
    expect(SRC).not.toMatch(/Search notes, name, address/);
  });

  it("no `sr-list-search` testid remains in the LIST source", () => {
    // The LIST is the only owner of that testid historically — a
    // bare grep is sufficient.
    expect(SRC).not.toMatch(/data-testid="sr-list-search"/);
  });

  it("no `q` / `qDebounced` state hooks remain in the LIST component", () => {
    // Pre-TD-75 the LIST declared `const [q, setQ] = useState("")`
    // and `const [qDebounced, setQDebounced] = useState("")`.
    expect(SRC).not.toMatch(/useState\(["']{2}\)\s*;?[\s\n]*\/\/[\s\S]{0,200}search/i);
    expect(SRC).not.toMatch(/\[\s*q\s*,\s*setQ\s*\]/);
    expect(SRC).not.toMatch(/\[\s*qDebounced\s*,\s*setQDebounced\s*\]/);
  });

  it("no `?q=` query-param construction remains in the LIST source", () => {
    // Pre-TD-75 the URL params effect emitted `sp.set("q", qDebounced)`.
    expect(SRC).not.toMatch(/sp\.set\(["']q["']/);
  });

  it("other filters (service_type + date range) survive untouched", () => {
    // Positive regression lock — the TD-75 removal is scoped.
    expect(SRC).toMatch(/data-testid="sr-list-filter-service-type"/);
    expect(SRC).toMatch(/data-testid="sr-list-filter-from"/);
    expect(SRC).toMatch(/data-testid="sr-list-filter-to"/);
    expect(SRC).toMatch(/data-testid="sr-list-filters"/);
  });

  it("filters bar grid collapsed from sm:grid-cols-4 to sm:grid-cols-2", () => {
    // Pre-TD-75 the search input ate `sm:col-span-2` on a 4-col grid.
    // Post-TD-75 the grid is a clean 2-col (service-type + dates).
    expect(SRC).not.toMatch(/sm:grid-cols-4[^"]*"[\s\S]{0,160}data-testid="sr-list-filters"/);
    expect(SRC).toMatch(/sm:grid-cols-2[\s\S]{0,160}data-testid="sr-list-filters"/);
    expect(SRC).not.toMatch(/sm:col-span-2/);
  });
});

// ────────────────────────────────────────────────────────────────
// 2. Instructional hint — darker-grey text-gray-700 lock.
// ────────────────────────────────────────────────────────────────
describe("TD-75 · instructional hint darker-grey (#374151) lock", () => {
  it("hint paragraph carries `text-gray-700` on its className", () => {
    // Match the <p> whose child text starts with "Click any visit"
    // and assert its className contains `text-gray-700`.
    const m = SRC.match(
      /<p\s+className="([^"]+)"[\s\S]{0,200}data-testid="service-reports-click-hint">\s*Click any visit/,
    );
    expect(m).not.toBeNull();
    expect(m[1].split(/\s+/)).toContain("text-gray-700");
  });

  it("hint no longer resolves `colors.muted` via inline style", () => {
    // Pre-TD-75 the hint used `style={{ color: colors.muted }}`.
    // Post-TD-75 the className owns the color so no inline style
    // for `color: colors.muted` should land on this element.
    const slice = SRC.match(
      /<p\s[\s\S]{0,400}data-testid="service-reports-click-hint">\s*Click any visit[\s\S]{0,120}<\/p>/,
    );
    expect(slice).not.toBeNull();
    expect(slice[0]).not.toMatch(/color:\s*colors\.muted/);
  });
});

// ────────────────────────────────────────────────────────────────
// 3. Rendered-DOM negative + positive locks on the actual page.
// ────────────────────────────────────────────────────────────────
const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: { get: (...a) => getSpy(...a), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({}),
}));

vi.mock("@/theme", () => {
  const base = {
    brand: "#0B4A6F", onBrand: "#FFFFFF", onSurface: "#111827",
    onSurfaceSecondary: "#6B7280", muted: "#6B7280", border: "#E5E7EB",
    divider: "#E5E7EB", surface: "#FFFFFF", surfaceSecondary: "#F8FAFC",
    success: "#059669",
  };
  return {
    colors: base,
    portalColors: base,
    portalGradients: { navyToBlue: { css: "linear-gradient(#000,#111)" } },
    money: (n) => `$${Number(n || 0).toFixed(2)}`,
  };
});

import { PortalServiceReports } from "@/pages/portal/PortalServiceReports";

describe("TD-75 · rendered DOM — search input absent, hint classed", () => {
  beforeEach(() => {
    getSpy.mockReset();
  });
  afterEach(() => { cleanup(); });

  it("the LIST renders with NO `sr-list-search` input and a hint that uses text-gray-700", async () => {
    getSpy.mockResolvedValue({
      items: [
        {
          id: "r1", job_id: "j1", job_title: "Weekly service",
          service_type: "pool_service",
          submitted_at: "2026-02-01T10:00:00Z",
          scheduled_start: "2026-02-01T09:00:00Z",
          tech_name: "Mike", customer_notes: "",
          water_bodies_summary: [], water_body_count: 0,
        },
      ],
      page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(<PortalServiceReports />);
    await waitFor(() => expect(getSpy).toHaveBeenCalled());

    // Search input absent.
    expect(screen.queryByTestId("sr-list-search")).toBeNull();

    // Hint present and carries `text-gray-700`.
    const hint = await screen.findByTestId("service-reports-click-hint");
    expect(hint).toBeTruthy();
    expect(hint.className.split(/\s+/)).toContain("text-gray-700");
  });

  it("the LIST fetch URL does not include a `q=` query param post-TD-75", async () => {
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(<PortalServiceReports />);
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const path = getSpy.mock.calls[0][0];
    expect(path).not.toMatch(/[?&]q=/);
    // page/page_size still land on the request.
    expect(path).toMatch(/page=1/);
    expect(path).toMatch(/page_size=20/);
  });
});
