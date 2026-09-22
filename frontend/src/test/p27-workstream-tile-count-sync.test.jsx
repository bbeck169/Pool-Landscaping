/**
 * Phase P27 · Feb-2026 — Workstream tile count sync + classifier fix.
 *
 * Locks the following contracts:
 *
 *   1. **Client-side derivation is the source of truth.** The tile
 *      pill's numeric contents are computed via ``useMemo`` over
 *      the SAME ``jobs`` array the list renders. There is NO
 *      separate summary-endpoint fetch feeding the tiles. Pre-P27
 *      the classifier's rule ordering silently dropped completed
 *      jobs whose ``service_type`` was empty — this test exercises
 *      the fix.
 *   2. **Empty-service_type completed rows count.** Rule #4 fallback
 *      fires BEFORE the empty-string guard so a completed job with
 *      an idiosyncratic (blank) ``service_type`` still counts as
 *      Services.
 *   3. **Filter chip re-derivation.** When the parent's filter
 *      hides N pending rows from the list, the tile totals reflect
 *      the new list — completed count preserved, total decrements.
 *   4. **New row added → tile increments.** A row pushed into the
 *      list (via mocked refetch) triggers the ``useMemo`` and the
 *      tile updates.
 *
 * Small-surface test — exercises ``computePillCounts`` + a Harness
 * that mimics ``WorkstreamPage.jsx``'s ``pillCounts`` +
 * ``JobCountPill`` wiring. Full-page mount of ``WorkstreamPage``
 * is 1500 LoC + Radix portals + 50 imports — the harness gives us
 * the same coverage without the collection cost.
 */
import React from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";

import { classifyJob, computePillCounts } from "@/lib/jobCategory";
import JobCountPill from "@/components/JobCountPill";


afterEach(() => {
  cleanup();
});


function _job({ id, status, service_type = "" }) {
  return { id, status, service_type };
}


function TileHarness({ jobs }) {
  // Mimic ``WorkstreamPage.jsx``:
  //   const pillCounts = useMemo(() => computePillCounts(jobs), [jobs]);
  //   <JobCountPill category="services" total remaining />
  const pillCounts = React.useMemo(() => computePillCounts(jobs), [jobs]);
  return (
    <div data-testid="workstream-count-pills">
      <JobCountPill
        category="services"
        total={pillCounts.services.total}
        remaining={pillCounts.services.remaining}
        testid="workstream-pill-services"
      />
      <JobCountPill
        category="repairs"
        total={pillCounts.repairs.total}
        remaining={pillCounts.repairs.remaining}
        testid="workstream-pill-repairs"
      />
      <div data-testid="job-list">
        {jobs.map((j) => (
          <span key={j.id} data-testid={`job-${j.id}`}>{j.id}</span>
        ))}
      </div>
    </div>
  );
}


describe("P27 · Classifier — empty-service_type completed fallback", () => {
  it("completed job with EMPTY service_type is classified as 'service'", () => {
    // Pre-P27 the ``if (!st) return null;`` guard at the top of
    // ``classifyJob`` short-circuited and dropped this row. P27
    // moves the ``_isCompleted`` fallback ABOVE the empty guard.
    expect(classifyJob({ id: "j1", status: "completed",
                          service_type: "" })).toBe("service");
    expect(classifyJob({ id: "j2", status: "completed" })).toBe("service");
  });

  it("non-completed job with empty service_type stays null", () => {
    expect(classifyJob({ id: "j1", status: "pending",
                          service_type: "" })).toBeNull();
    expect(classifyJob({ id: "j2", status: "scheduled" })).toBeNull();
  });

  it("classifier is case-insensitive on status (matches backend regex)", () => {
    // Backend now emits title-case Completed via legacy migrations
    // through the case-insensitive regex; classifier must agree.
    expect(classifyJob({ id: "j1", status: "Completed",
                          service_type: "" })).toBe("service");
    expect(classifyJob({ id: "j2", status: "COMPLETED",
                          service_type: "Weird Custom Type" })).toBe("service");
  });

  it("repairs still win on ambiguous 'pool repair' style rows", () => {
    expect(classifyJob({ id: "j1", status: "completed",
                          service_type: "Pool Repair" })).toBe("repair");
    expect(classifyJob({ id: "j2", status: "pending",
                          service_type: "Fix Broken Pump" })).toBe("repair");
  });
});


describe("P27 · computePillCounts — empty-service_type fallback rescued", () => {
  it("counts a completed empty-service_type row into services totals", () => {
    const jobs = [
      _job({ id: "a", status: "completed", service_type: "Weekly Pool Service" }),
      _job({ id: "b", status: "completed", service_type: "" }),  // empty!
      _job({ id: "c", status: "completed", service_type: "Pool Repair" }),
    ];
    const counts = computePillCounts(jobs);
    // Rescued: services.total = 2 (Weekly Pool Service + empty rule-4).
    expect(counts.services.total).toBe(2);
    // Both completed → remaining = 0.
    expect(counts.services.remaining).toBe(0);
    expect(counts.repairs.total).toBe(1);
    expect(counts.repairs.remaining).toBe(0);
  });
});


describe("P27 · Tile count sync — derived from filtered list", () => {
  it("mounts with 23 jobs (5 completed, 18 pending); tile shows 18/23 remaining", () => {
    // 23 jobs: 5 completed services + 18 pending services.
    const jobs = [];
    for (let i = 0; i < 5; i++) {
      jobs.push(_job({
        id: `c${i}`, status: "completed", service_type: "Weekly Pool Service",
      }));
    }
    for (let i = 0; i < 18; i++) {
      jobs.push(_job({
        id: `p${i}`, status: "pending", service_type: "Weekly Pool Service",
      }));
    }
    render(<TileHarness jobs={jobs} />);

    // Total = 23, remaining = 18 (only completed ones don't count as
    // remaining; the copy is ``<remaining>/<total>`` per JobCountPill).
    expect(
      screen.getByTestId("workstream-pill-services-total").textContent,
    ).toBe("23");
    expect(
      screen.getByTestId("workstream-pill-services-remaining").textContent,
    ).toBe("18");
    expect(
      screen.getByTestId("workstream-pill-services-label").textContent,
    ).toBe("SERVICES");
  });

  it("filter chip hides 10 pending rows → tile updates to 8/13", () => {
    // Start with 23 rows (5 completed, 18 pending), then re-render
    // with only 13 (5 completed, 8 pending) as if a filter chip
    // dropped 10 pending.
    const full = [];
    for (let i = 0; i < 5; i++) {
      full.push(_job({
        id: `c${i}`, status: "completed", service_type: "Weekly Pool Service",
      }));
    }
    for (let i = 0; i < 18; i++) {
      full.push(_job({
        id: `p${i}`, status: "pending", service_type: "Weekly Pool Service",
      }));
    }

    const { rerender } = render(<TileHarness jobs={full} />);
    expect(
      screen.getByTestId("workstream-pill-services-total").textContent,
    ).toBe("23");

    // Filter chip hides 10 pending rows (indices 8..17).
    const filtered = full.filter(
      (j, i) => j.status !== "pending" || i < 5 + 8,
    );
    expect(filtered.length).toBe(13);
    act(() => {
      rerender(<TileHarness jobs={filtered} />);
    });

    // Total = 13, remaining = 8 (the 8 remaining pendings).
    expect(
      screen.getByTestId("workstream-pill-services-total").textContent,
    ).toBe("13");
    expect(
      screen.getByTestId("workstream-pill-services-remaining").textContent,
    ).toBe("8");
    // Repairs pill untouched.
    expect(
      screen.getByTestId("workstream-pill-repairs-total").textContent,
    ).toBe("0");
  });

  it("push a new job into the list → tile increments in same render cycle", () => {
    const start = [
      _job({ id: "a", status: "completed", service_type: "Pool Service" }),
      _job({ id: "b", status: "pending", service_type: "Pool Service" }),
    ];
    const { rerender } = render(<TileHarness jobs={start} />);
    expect(
      screen.getByTestId("workstream-pill-services-total").textContent,
    ).toBe("2");
    expect(
      screen.getByTestId("workstream-pill-services-remaining").textContent,
    ).toBe("1");

    // Mock a WS push / refetch: parent bumps ``jobs`` with a new
    // completed row. The tile's ``useMemo`` MUST re-derive.
    const nextJobs = [
      ...start,
      _job({ id: "c", status: "completed", service_type: "Landscaping" }),
    ];
    act(() => { rerender(<TileHarness jobs={nextJobs} />); });

    expect(
      screen.getByTestId("workstream-pill-services-total").textContent,
    ).toBe("3");
    expect(
      screen.getByTestId("workstream-pill-services-remaining").textContent,
    ).toBe("1");
  });

  it("empty jobs list → tile shows 0/0 without crash", () => {
    render(<TileHarness jobs={[]} />);
    expect(
      screen.getByTestId("workstream-pill-services-total").textContent,
    ).toBe("0");
    expect(
      screen.getByTestId("workstream-pill-services-remaining").textContent,
    ).toBe("0");
    expect(
      screen.getByTestId("workstream-pill-repairs-total").textContent,
    ).toBe("0");
  });
});


describe("P27 · No separate summary endpoint in render path", () => {
  it("WorkstreamPage source does not fetch /workstream/summary", () => {
    // Guardrail via a synchronous read of the WorkstreamPage
    // source (not a runtime test — the page-level render is
    // deferred to the k12 test suite). This catches a regression
    // where someone re-introduces a summary fetch that could
    // drift from the filtered list.
    //
    // Uses a dynamic import so the vitest transform picks up the
    // file's contents without executing its side effects.
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/workstream/WorkstreamPage.jsx"),
      "utf8",
    );
    expect(src.includes("/workstream/summary")).toBe(false);
    // Tile counts derivation MUST be a useMemo over jobs.
    expect(src.includes(
      "useMemo(() => computePillCounts(jobs), [jobs])"
    )).toBe(true);
  });
});
