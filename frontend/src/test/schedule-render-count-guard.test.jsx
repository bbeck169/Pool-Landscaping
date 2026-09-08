/**
 * Feb-2026 · P0 defensive · Schedule render-count invariant.
 *
 * H3 hypothesis in the P0 diagnostic — "React infinite render
 * loop from a token cascade or role-check hook, only surfaces
 * when a job row is present" — was rejected by evidence in the
 * live repro but the failure mode is easy to re-introduce with a
 * bad ``useEffect`` dep list. This test pins the invariant so a
 * future PR that adds a state-writing effect inside the schedule
 * row render tree (or its shared hooks) trips this guard.
 *
 * Invariant enforced:
 *   * A parent that renders N job rows AND drives the
 *     ``useNumberedOrder`` reorder hook MUST NOT render any
 *     individual row more than 3 times on mount. React 18
 *     StrictMode double-invokes effects, which tolerates 2 renders
 *     per row per mount cycle; a 3rd render represents "state
 *     churn that stabilises within one tick"; anything above 3
 *     signals an unstable dep list (the H3 failure mode).
 *
 * The test intentionally exercises the REAL
 * ``useNumberedOrder`` from
 * ``src/pages/schedule/NumberedReorder.jsx`` — not a fake — so any
 * regression there (e.g., someone adds ``[jobs, opts]`` to a dep
 * array by accident) surfaces here.
 */
import React, { useRef } from "react";
import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { useNumberedOrder } from
  "../pages/schedule/NumberedReorder";


const _JOBS = [
  { id: "j-1", customer_name: "A", route_order: 1, status: "scheduled" },
  { id: "j-2", customer_name: "B", route_order: 2, status: "scheduled" },
  { id: "j-3", customer_name: "C", route_order: 3, status: "scheduled" },
  { id: "j-4", customer_name: "D", route_order: 4, status: "scheduled" },
  { id: "j-5", customer_name: "E", route_order: 5, status: "scheduled" },
];


function _Row({ job, renderCounts }) {
  // Track how many times this row instance re-rendered.
  const cnt = useRef(0);
  cnt.current += 1;
  renderCounts[job.id] = cnt.current;
  return (
    <div data-testid={`row-${job.id}`}>
      {job.customer_name}
    </div>
  );
}


/** Minimal analog of the ``<GridPanel>`` job-row loop inside
 *  ``CalendarSchedule.jsx``.  Drives the same reorder hook so
 *  any dep-list churn there gets counted through the rows. */
function _GridPanelProbe({ jobs, renderCounts }) {
  const controller = useNumberedOrder(jobs, {
    autoSave: true,
    techUserId: "u-1",
    date: "2026-02-10",
  });
  // Access one field off the controller so the probe re-renders
  // on any controller state change (mirroring the real GridPanel
  // which reads ``drafts`` + ``validation`` on every render).
  const _draftsCount = Object.keys(controller.drafts || {}).length;
  return (
    <div data-drafts-count={_draftsCount}>
      {jobs.map((j) => (
        <_Row key={j.id} job={j} renderCounts={renderCounts} />
      ))}
    </div>
  );
}


describe("schedule render-count invariant (H3 regression guard)", () => {
  it("renders each job row ≤ 4 times on mount " +
       "(StrictMode double-invoke + one hook-driven refresh " +
       "tolerated; prod without StrictMode settles at 2)", () => {
    const counts = {};
    render(
      <React.StrictMode>
        <_GridPanelProbe jobs={_JOBS} renderCounts={counts} />
      </React.StrictMode>,
    );
    // Sanity — every row rendered at least once.
    for (const j of _JOBS) {
      expect(counts[j.id]).toBeGreaterThanOrEqual(1);
    }
    // Invariant — no row rendered more than 4 times. 4 is the
    // ceiling because:
    //   * 1 = initial render
    //   * 2 = StrictMode double-invoke of the initial render
    //   * 3 = useNumberedOrder's mount effect calls setDrafts
    //         once (line 162-175 of NumberedReorder.jsx — refresh
    //         the draft map from a new jobs identity)
    //   * 4 = StrictMode re-runs that same effect once more
    // Anything above 4 = the row is churning on every effect
    // tick, i.e. the H3 failure mode. Real prod (no StrictMode)
    // will settle at 2 renders per row.
    for (const j of _JOBS) {
      expect(counts[j.id]).toBeLessThanOrEqual(4);
    }
  });

  it("renders each job row ≤ 4 times even on a 25-row day " +
       "(scale guard — prod tenants routinely have 20+ jobs/day)",
     () => {
    const many = Array.from({ length: 25 }, (_, i) => ({
      id: `j-${i}`,
      customer_name: `Customer ${i}`,
      route_order: i,
      status: "scheduled",
    }));
    const counts = {};
    render(
      <React.StrictMode>
        <_GridPanelProbe jobs={many} renderCounts={counts} />
      </React.StrictMode>,
    );
    for (const j of many) {
      expect(counts[j.id]).toBeLessThanOrEqual(4);
    }
  });

  it("does NOT loop when the jobs list is empty " +
       "(the H3 report was ``freezes if any day has a job``, so " +
       "empty must stay stable too)", () => {
    const counts = {};
    render(
      <React.StrictMode>
        <_GridPanelProbe jobs={[]} renderCounts={counts} />
      </React.StrictMode>,
    );
    // No rows → no counts.
    expect(Object.keys(counts).length).toBe(0);
  });
});
