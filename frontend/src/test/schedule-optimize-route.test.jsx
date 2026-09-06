/**
 * Feb-2026 · Optimize Route — frontend contract tests.
 *
 * Covers the two seams the P0/P2/feature ship touched:
 *   1. ``useNumberedOrder`` — when ``initialOrder`` is passed, the
 *      drafts map is seeded 1..N against the optimizer's ordering,
 *      NOT by ``route_index``. Without this the modal renders the
 *      old (pre-optimization) order and the pre-fill silently no-ops.
 *   2. ``BulkReorderModal`` — renders the summary banner + the
 *      Haversine-fallback warning banner when the optimizer payload
 *      indicates a fallback. Testids for the banner + the trigger
 *      button live in ``CalendarSchedule.jsx`` and are asserted by a
 *      source-string guard here (rendering the full schedule page
 *      hangs under jsdom — same jsdom-modal-fetch pattern the P0
 *      typed-confirm tests already document).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";


const { apiGetMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: apiGetMock, post: apiPostMock,
    put: vi.fn(), patch: vi.fn(), del: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import {
  useNumberedOrder, BulkReorderModal,
} from "@/pages/schedule/NumberedReorder";


const JOBS = [
  { id: "j-a", route_index: 0, customer_name: "Alpha",
    address: "1 A St", scheduled_time: "09:00" },
  { id: "j-b", route_index: 1, customer_name: "Bravo",
    address: "2 B St", scheduled_time: "10:00" },
  { id: "j-c", route_index: 2, customer_name: "Charlie",
    address: "3 C St", scheduled_time: "11:00" },
];


beforeEach(() => {
  vi.clearAllMocks();
});


// ── Layer 1 · useNumberedOrder initialOrder seeding ───────────────
function Harness({ jobs, initialOrder }) {
  const ctrl = useNumberedOrder(jobs, { autoSave: false, initialOrder });
  return (
    <ul>
      {jobs.map((j) => (
        <li key={j.id} data-testid={`draft-${j.id}`}>
          {ctrl.drafts[j.id] || ""}
        </li>
      ))}
    </ul>
  );
}


describe("useNumberedOrder · initialOrder seeding", () => {
  it("without initialOrder — seeds by route_index (baseline)", () => {
    render(<Harness jobs={JOBS} initialOrder={null} />);
    expect(screen.getByTestId("draft-j-a").textContent).toBe("1");
    expect(screen.getByTestId("draft-j-b").textContent).toBe("2");
    expect(screen.getByTestId("draft-j-c").textContent).toBe("3");
  });

  it("with initialOrder — reseeds drafts against the optimized order", () => {
    // Optimizer says C, A, B is the best sequence.
    render(<Harness jobs={JOBS} initialOrder={["j-c", "j-a", "j-b"]} />);
    expect(screen.getByTestId("draft-j-c").textContent).toBe("1");
    expect(screen.getByTestId("draft-j-a").textContent).toBe("2");
    expect(screen.getByTestId("draft-j-b").textContent).toBe("3");
  });

  it("jobs not present in initialOrder get a tail number", () => {
    // Optimizer knows about j-a and j-b only. j-c falls to the tail.
    render(<Harness jobs={JOBS} initialOrder={["j-b", "j-a"]} />);
    expect(screen.getByTestId("draft-j-b").textContent).toBe("1");
    expect(screen.getByTestId("draft-j-a").textContent).toBe("2");
    // j-c → initialOrder.length + 1 = 3.
    expect(screen.getByTestId("draft-j-c").textContent).toBe("3");
  });
});


// ── Layer 2 · BulkReorderModal summary + warning banners ──────────
describe("BulkReorderModal · Optimize Route banners", () => {
  it("renders summary banner when optimizeSummary is passed", () => {
    render(
      <BulkReorderModal
        jobs={JOBS}
        techUserId={"u-1"}
        date={"2026-02-20"}
        initialOrder={["j-c", "j-a", "j-b"]}
        optimizeSummary={"Estimated ~1h 20m · 12.4mi · directions_v2+orion_bias"}
        optimizeWarnings={[]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );
    const banner = screen.getByTestId("id-optimize-route-summary");
    expect(banner).toBeTruthy();
    expect(banner.textContent).toContain("~1h 20m");
    expect(banner.textContent).toContain("directions_v2+orion_bias");
    // No fallback banner when warnings don't mention Directions.
    expect(screen.queryByTestId("id-optimize-route-warning")).toBeNull();
  });

  it("renders the fallback warning when a warning mentions 'Directions unavailable'", () => {
    render(
      <BulkReorderModal
        jobs={JOBS}
        techUserId={"u-1"}
        date={"2026-02-20"}
        initialOrder={["j-a", "j-b", "j-c"]}
        optimizeSummary={"Estimated ~1h 20m · 12.4mi · haversine_fallback"}
        optimizeWarnings={["Directions unavailable — using Haversine fallback. Review order manually."]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );
    const w = screen.getByTestId("id-optimize-route-warning");
    expect(w).toBeTruthy();
    expect(w.textContent).toContain("Directions unavailable");
    // Summary still renders alongside the warning.
    expect(screen.getByTestId("id-optimize-route-summary")).toBeTruthy();
  });

  it("renders no banners when optimize props are absent (existing Reorder flow)", () => {
    render(
      <BulkReorderModal
        jobs={JOBS}
        techUserId={"u-1"}
        date={"2026-02-20"}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("id-optimize-route-summary")).toBeNull();
    expect(screen.queryByTestId("id-optimize-route-warning")).toBeNull();
  });
});


// ── Layer 3 · CalendarSchedule source-string guards ───────────────
// Mounting <CalendarSchedule /> under jsdom hangs (router+fetch+modal
// heavy). Source-string guards lock the wire-up shape so a future
// refactor can't silently drop the Optimize button or its POST call.
describe("CalendarSchedule · Optimize Route wire-up (source guard)", () => {
  const src = readFileSync(
    resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"), "utf8",
  );

  it("declares the id-optimize-route-btn with the same admin gate as Reorder", () => {
    expect(src).toMatch(/data-testid="id-optimize-route-btn"/);
    // Gate: disabled when <2 stops OR not admin OR busy OR optimizing.
    expect(src).toMatch(
      /disabled=\{[^}]*optimizing[^}]*isAdminForCard[^}]*reorderableJobIds[^}]*length\s*<\s*2/,
    );
  });

  it("POSTs to /schedule/optimize-route with date + technician_id payload", () => {
    // The exact endpoint + payload shape the backend contract expects.
    expect(src).toMatch(/api\.post\(\s*["']\/schedule\/optimize-route["']/);
    expect(src).toMatch(/date:\s*focusISO/);
    expect(src).toMatch(/technician_id:\s*_dayTechHint/);
  });

  it("threads initialOrder + optimizeSummary + optimizeWarnings into BulkReorderModal", () => {
    expect(src).toMatch(/initialOrder=\{optimizePayload\?\.orderedIds/);
    expect(src).toMatch(/optimizeSummary=\{optimizePayload\?\.summary/);
    expect(src).toMatch(/optimizeWarnings=\{optimizePayload\?\.warnings/);
  });

  it("clears optimizePayload on modal close AND on save (Cancel discards, Save consumes)", () => {
    // Close handler: setOptimizePayload(null).
    expect(src).toMatch(/onClose=\{[^}]*setOptimizePayload\(null\)/);
    // Save handler: setOptimizePayload(null) then reload.
    expect(src).toMatch(/onSaved=\{[^}]*setOptimizePayload\(null\)/);
  });

  it("Reorder button opens the modal WITHOUT the optimize payload (independent flow)", () => {
    // The Reorder button's onOpenBulkReorder must clear
    // optimizePayload so opening Reorder-then-Save doesn't
    // accidentally apply the last optimize suggestion.
    expect(src).toMatch(
      /onOpenBulkReorder=\{\(\)\s*=>\s*\{\s*setOptimizePayload\(null\)\s*;\s*setBulkReorderOpen\(true\)/,
    );
  });
});
