/**
 * Phase P10 · Feb-2026 — Schedule Reorder · Crew/Tech Lane Fix (vitest).
 *
 * Locks in the four frontend acceptance points:
 *
 *   1. ``useNumberedOrder.save()`` surfaces the widened backend's
 *      ``409 reorder_lane_mismatch`` via the dedicated lane banner
 *      (never the generic red toast).
 *   2. Same for the single-row ``insertShift()`` path — a
 *      ``409 reorder_unassigned_job`` from ``/jobs/reorder-day-route``
 *      raises the lane banner with the "Assign a technician or crew…"
 *      call-to-action.
 *   3. ``<ReorderErrorBanner />`` renders when the hook raises a
 *      lane-scope error AND dismisses cleanly on the × button.
 *   4. The banner's error text ships the canonical strings that the
 *      Reorder button's disabled-tooltip also uses (via the exported
 *      module constants) — so the two surfaces stay in lock-step.
 *
 * The mixed-lane / has-unassigned drop-target disabling in
 * ``CalendarSchedule.jsx`` is verified via a source-scan (the
 * component is >3 kLOC and pulls in react-big-calendar +
 * @vis.gl/react-google-maps, so we don't mount the full page in
 * this suite — the module-scope constant re-use is the invariant
 * that couples the two surfaces).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";


const _h = vi.hoisted(() => ({
  post: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { post: _h.post, get: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f7f7f7", border: "#e2e2e2",
    onSurface: "#111", muted: "#666", brand: "#0891B2", error: "#DC2626",
    text: "#111",
  },
  font: { family: "system-ui" },
}));

import {
  useNumberedOrder,
  NumberOrderInput,
  ReorderErrorBanner,
  REORDER_LANE_ERROR_TEXT,
  REORDER_MIXED_LANE_ERROR_TEXT,
} from "@/pages/schedule/NumberedReorder";


/** Build the Error the real ``api.js`` throws on a 409:
 *    * ``err.message`` = the FastAPI ``detail.code`` string.
 *    * ``err.status``  = 409.
 *    * ``err.data``    = the parsed body ``{ detail: {...} }``.
 *  This mirrors ``api.js`` lines 226-266 so the hook's error-shape
 *  probing is exercised exactly as it runs live. */
function _mk409(code, extra = {}) {
  const detail = { code, lane_id: "tech-1", ...extra };
  const err = new Error(code);
  err.status = 409;
  err.data = { detail };
  return err;
}


/** Thin harness that exposes the hook so tests can drive it like a
 *  real card-list. Renders one NumberOrderInput per job + the
 *  ReorderErrorBanner (the lane-scope surface). */
const DEFAULT_JOBS = [
  { id: "j1", route_index: 0, customer_name: "Alpha", status: "scheduled",
    technician_id: "tech-1", scheduled_date: "2026-03-15" },
  { id: "j2", route_index: 1, customer_name: "Bravo", status: "scheduled",
    technician_id: "tech-1", scheduled_date: "2026-03-15" },
];

function Harness({ jobs = DEFAULT_JOBS, ...opts }) {
  const controller = useNumberedOrder(jobs, {
    autoSave: true, techUserId: "tech-1", date: "2026-03-15", ...opts,
  });
  return (
    <div>
      <ReorderErrorBanner controller={controller} />
      {jobs.map((j) => (
        <div key={j.id} data-testid={`row-${j.id}`}>
          <NumberOrderInput job={j} controller={controller} />
        </div>
      ))}
      <button
        data-testid="probe-save"
        onClick={() => controller.save()}
      >
        save
      </button>
    </div>
  );
}


beforeEach(() => {
  _h.post.mockReset();
});


describe("Phase P10 · lane-scope error surfacing", () => {
  it("bulk save · 409 reorder_lane_mismatch raises the dedicated lane banner (not the generic toast)", async () => {
    _h.post.mockRejectedValueOnce(_mk409("reorder_lane_mismatch", {
      missing_job_ids: ["j-carlos"],
    }));

    render(<Harness />);

    // Fire the bulk-save path — payload is valid client-side (both
    // drafts stay at their prefill values). The mocked API rejects
    // with the widened 409.
    await act(async () => {
      fireEvent.click(screen.getByTestId("probe-save"));
    });

    // The banner renders with the canonical copy.
    await waitFor(() => {
      expect(screen.getByTestId("reorder-error-banner")).toBeTruthy();
    });
    expect(screen.getByTestId("reorder-error-banner").textContent)
      .toContain(REORDER_LANE_ERROR_TEXT);
    // Generic red toast is silenced — no ``route-order-error-banner``
    // (that's ``ReorderBanner``, the pre-P10 surface).
    expect(screen.queryByTestId("route-order-error-banner")).toBeNull();

    // The POST was fired exactly once — the retry-on-409 path is
    // intentionally NOT there (would cause an infinite loop on a
    // truly stuck lane_id).
    expect(_h.post).toHaveBeenCalledTimes(1);
    expect(_h.post).toHaveBeenCalledWith(
      "/jobs/reorder",
      expect.objectContaining({ tech_user_id: "tech-1" }),
    );
  });

  it("bulk save · 409 reorder_unassigned_job raises the dedicated lane banner", async () => {
    _h.post.mockRejectedValueOnce(_mk409("reorder_unassigned_job", {
      job_ids: ["ghost"],
    }));

    render(<Harness />);

    await act(async () => {
      fireEvent.click(screen.getByTestId("probe-save"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("reorder-error-banner")).toBeTruthy();
    });
    // Same canonical copy — the code differs but the operator-facing
    // guidance is identical (assign a tech or crew).
    expect(screen.getByTestId("reorder-error-banner").textContent)
      .toContain(REORDER_LANE_ERROR_TEXT);
  });

  it("single-row insertShift · 409 lane_mismatch raises the lane banner (mirrors bulk save)", async () => {
    // First POST: /jobs/reorder-day-route → 409.
    _h.post.mockRejectedValueOnce(_mk409("reorder_lane_mismatch"));

    render(<Harness />);
    const i1 = screen.getByTestId("route-order-input-j1");

    // Focus then bump the value so blurSave fires the single-row
    // insert-shift path (touchedJobId path in NumberedReorder).
    await act(async () => {
      fireEvent.focus(i1);
      fireEvent.change(i1, { target: { value: "9" } });
      fireEvent.blur(i1);
    });

    await waitFor(() => {
      expect(screen.getByTestId("reorder-error-banner")).toBeTruthy();
    });
    expect(_h.post).toHaveBeenCalledWith(
      "/jobs/reorder-day-route",
      expect.objectContaining({
        job_id: "j1",
        technician_id: "tech-1",
        date: "2026-03-15",
      }),
    );
  });

  it("banner × button dismisses the lane banner", async () => {
    _h.post.mockRejectedValueOnce(_mk409("reorder_lane_mismatch"));

    render(<Harness />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("probe-save"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("reorder-error-banner")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("reorder-error-banner-dismiss"));
    });
    expect(screen.queryByTestId("reorder-error-banner")).toBeNull();
  });

  it("banner value= prop path (client-side mixed-lane force-open) renders the mixed-lane copy", () => {
    // The CalendarSchedule "day spans multiple lanes" case uses
    // ``value=`` on the banner (no API call needed) so the operator
    // can see WHY the Reorder button is disabled even before they
    // click. Verify the primitive supports that path.
    render(
      <ReorderErrorBanner
        value={{ code: "mixed_lanes_client", text: REORDER_MIXED_LANE_ERROR_TEXT }}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByTestId("reorder-error-banner").textContent)
      .toContain(REORDER_MIXED_LANE_ERROR_TEXT);
  });

  it("banner value= prop can be dismissed via onDismiss callback", () => {
    const onDismiss = vi.fn();
    render(
      <ReorderErrorBanner
        value={{ code: "mixed_lanes_client", text: REORDER_MIXED_LANE_ERROR_TEXT }}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByTestId("reorder-error-banner-dismiss"));
    expect(onDismiss).toHaveBeenCalled();
  });
});


describe("Phase P10 · CalendarSchedule drop-target gating (source-scan)", () => {
  it("Reorder button is disabled when reorderLaneStatus is mixed_lanes / has_unassigned", async () => {
    // ``CalendarSchedule.jsx`` is a >3 kLOC surface — instead of
    // mounting it we scan the source for the exact ``disabled=``
    // conjunction on ``data-testid=\"grid-bulk-reorder\"``. If
    // someone drops the mixed_lanes / has_unassigned guard from the
    // button, this test fails.
    const fs = await import("fs");
    const path = await import("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "..", "pages", "schedule", "CalendarSchedule.jsx"),
      "utf-8",
    );
    // Locate the ``grid-bulk-reorder`` button block. Regex is
    // deliberately generous on whitespace so a minor reformat
    // doesn't tank the test — the invariant we care about is the
    // two guard clauses appearing in the button's disabled expr.
    const idx = src.indexOf("data-testid=\"grid-bulk-reorder\"");
    expect(idx).toBeGreaterThan(0);
    // Peek at the ~1 kB slab BEFORE the testid — that's where the
    // ``disabled={...}`` prop and its inline-style ``opacity``
    // ternary live for the Reorder button.
    const slab = src.slice(Math.max(0, idx - 900), idx);
    expect(slab).toContain("reorderLaneStatus === \"mixed_lanes\"");
    expect(slab).toContain("reorderLaneStatus === \"has_unassigned\"");
  });

  it("orderController is scoped to a single lane (no cross-lane payload construction)", async () => {
    // The mitigation: when the day mixes lanes, the parent hands
    // the hook an EMPTY jobs list so ``save()`` / ``insertShift()``
    // physically can't construct a cross-lane request. Verify the
    // ``_reorderScopedJobs`` memo returns ``[]`` unless
    // ``reorderLaneStatus === "ready"``.
    const fs = await import("fs");
    const path = await import("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "..", "pages", "schedule", "CalendarSchedule.jsx"),
      "utf-8",
    );
    // The invariant: the empty-list return path is present.
    expect(src).toMatch(
      /_reorderScopedJobs\s*=\s*React\.useMemo\([\s\S]*?if\s*\(\s*reorderLaneStatus\s*!==\s*"ready"\s*\)\s*return\s*\[\]/,
    );
  });
});


describe("Phase P10 · error-shape robustness", () => {
  it("hook parses the 409 code from err.data.detail.code (api.js contract)", async () => {
    // Regression: an earlier P10 draft checked ``err.body.detail.code``
    // but ``api.js`` attaches the parsed body under ``err.data``.
    // Simulate the real error shape and prove the banner fires.
    const err = new Error("reorder_lane_mismatch");
    err.status = 409;
    err.data = { detail: { code: "reorder_lane_mismatch", lane_id: "x" } };
    _h.post.mockRejectedValueOnce(err);

    render(<Harness />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("probe-save"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("reorder-error-banner")).toBeTruthy();
    });
  });

  it("hook also handles legacy err.body.detail.code shape", async () => {
    const err = new Error("Request failed (409)");
    err.status = 409;
    err.body = { detail: { code: "reorder_unassigned_job" } };
    _h.post.mockRejectedValueOnce(err);

    render(<Harness />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("probe-save"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("reorder-error-banner")).toBeTruthy();
    });
  });
});
