/**
 * Phase P28 · Feb-2026 — JobTimersPage 30-day default + Phase-2 note removal.
 *
 * Locks the following contracts:
 *
 *   1. **Default range = last 30 days.** ``_defaultRange`` returns
 *      ``{ date_from: today - 30d, date_to: today }`` in the tenant's
 *      timezone. The rendered ``jt-filter-from`` / ``jt-filter-to``
 *      inputs land on those exact values.
 *   2. **No Phase-2 / geofencing note in the DOM.** Grepping the
 *      rendered HTML for ``"Phase 2"``, ``"ships in Phase"``, and
 *      ``"geofence auto-start"`` returns zero hits.
 *   3. **Manual range picker still works** — the "From" / "To" date
 *      inputs are mounted; a change event flows into ``filters``
 *      and updates the input's rendered value.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── API mock (same shape as job-timers-dashboard.test.jsx) ───────
let _listResp = {
  items: [], count: 0, page: 1, page_size: 25, total: 0, total_pages: 1,
};
let _summaryResp = {
  avg_seconds: 0, count: 0, min_seconds: 0, max_seconds: 0,
  median_seconds: 0,
};

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/job-timers/summary")) return _summaryResp;
      if (path.startsWith("/job-timers/aggregates"))
        return { buckets: [], totals: null };
      if (path.startsWith("/job-timers"))       return _listResp;
      if (path === "/auth/me")                  return { role: "super_admin" };
      return {};
    }),
    post: vi.fn(), patch: vi.fn(), delete: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

// scrollIntoView isn't in jsdom.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}


import JobTimersPage from "@/pages/timers/JobTimersPage";


// ── Helpers ──────────────────────────────────────────────────────


function _isoInTZ(d, tz = "America/Phoenix") {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(d);
  const y = parts.find((p) => p.type === "year")?.value;
  const m = parts.find((p) => p.type === "month")?.value;
  const day = parts.find((p) => p.type === "day")?.value;
  return `${y}-${m}-${day}`;
}


beforeEach(() => {
  // Fake timers with real-time advance so ``waitFor`` /
  // ``findByTestId`` polling still fires. ``setSystemTime`` gives
  // us the deterministic pin for the 30-day math; ``shouldAdvance
  // Time`` keeps the async layer alive.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-02-15T12:00:00Z"));
});


afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  cleanup();
});


// ── 1) Default range = last 30 days in tenant tz ────────────────


describe("P28 · JobTimersPage default range", () => {
  it("renders with date_from = today − 30d and date_to = today (tenant tz)", async () => {
    render(
      <MemoryRouter initialEntries={["/dashboard/job-timers"]}>
        <JobTimersPage />
      </MemoryRouter>,
    );

    // The filter inputs are ``type="date"`` — their ``value`` is
    // whatever the state initializer produced.
    const now = new Date("2026-02-15T12:00:00Z");
    const past = new Date(now);
    past.setDate(now.getDate() - 30);
    const expected_from = _isoInTZ(past);
    const expected_to   = _isoInTZ(now);

    // Sanity — the math must produce a 30-day gap. In Feb the
    // month rolls back cleanly.
    expect(expected_to).toBe("2026-02-15");
    expect(expected_from).toBe("2026-01-16");

    const from_input = await screen.findByTestId("jt-filter-from");
    const to_input   = await screen.findByTestId("jt-filter-to");
    expect(from_input.value).toBe(expected_from);
    expect(to_input.value).toBe(expected_to);
  });
});


// ── 2) Phase-2 / geofencing note removed ─────────────────────────


describe("P28 · Phase-2 geofencing note removed", () => {
  it("does NOT render the pre-P28 Phase 2 note anywhere in the page", async () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/dashboard/job-timers"]}>
        <JobTimersPage />
      </MemoryRouter>,
    );

    // Wait for the initial page paint so any late-hydrated
    // banners have a chance to render.
    await waitFor(() =>
      expect(screen.getByTestId("job-timers-page")).toBeTruthy(),
    );

    const html = container.innerHTML;
    expect(html).not.toMatch(/Phase 2/i);
    expect(html).not.toMatch(/ships in Phase/i);
    expect(html).not.toMatch(/geofence auto-start/i);
  });

  it("preserves the surrounding retrospective-view copy", async () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/dashboard/job-timers"]}>
        <JobTimersPage />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("job-timers-page")).toBeTruthy(),
    );
    // The retrospective-view intro line MUST still render — P28
    // only trims the trailing "Mobile GPS geofence auto-start ships
    // in Phase 2." sentence, not the whole paragraph.
    expect(container.innerHTML).toMatch(/Retrospective view of/);
    expect(container.innerHTML).toMatch(/service-report submit/);
  });
});


// ── 3) Manual range picker still works ───────────────────────────


describe("P28 · Manual range picker regression guard", () => {
  it("changing the ``From`` input updates the rendered value", async () => {
    render(
      <MemoryRouter initialEntries={["/dashboard/job-timers"]}>
        <JobTimersPage />
      </MemoryRouter>,
    );
    const from_input = await screen.findByTestId("jt-filter-from");
    fireEvent.change(from_input, { target: { value: "2026-01-01" } });
    expect(from_input.value).toBe("2026-01-01");
  });

  it("changing the ``To`` input updates the rendered value", async () => {
    render(
      <MemoryRouter initialEntries={["/dashboard/job-timers"]}>
        <JobTimersPage />
      </MemoryRouter>,
    );
    const to_input = await screen.findByTestId("jt-filter-to");
    fireEvent.change(to_input, { target: { value: "2026-02-01" } });
    expect(to_input.value).toBe("2026-02-01");
  });

  it("date-input testids for both bookend selectors are present", async () => {
    render(
      <MemoryRouter initialEntries={["/dashboard/job-timers"]}>
        <JobTimersPage />
      </MemoryRouter>,
    );
    // Both the primary testid AND the alias legacy tests key on.
    expect(await screen.findByTestId("jt-filter-from")).toBeTruthy();
    expect(await screen.findByTestId("jt-filter-to")).toBeTruthy();
    // The hidden alias-marker for legacy tests.
    expect(
      await screen.findByTestId("job-timers-filter-from"),
    ).toBeTruthy();
  });
});
