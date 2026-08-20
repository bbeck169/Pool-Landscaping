/**
 * Feb-2026 · Numbered-order schedule reorder — vitest.
 *
 * Locks in the numeric-input replacement for the DnD reorder.
 * Because ``CalendarSchedule.jsx`` is a 2,000-line surface that
 * pulls in react-big-calendar + @vis.gl/react-google-maps, we do
 * NOT mount the full page here. Instead we exercise the
 * ``NumberedReorder`` primitives (hook + input + banner + modal)
 * directly — the schedule page just wires them in. Full-page
 * behavior is covered by the visual smoke screenshot and by the
 * existing ``schedule-dnd-and-import.test.jsx`` regression guard.
 */
import React, { useState } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";


/* ── Hoisted mocks ────────────────────────────────────────── */

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
  ReorderBanner,
  BulkReorderModal,
} from "@/pages/schedule/NumberedReorder";


const JOBS = [
  { id: "j1", route_index: 0, customer_name: "Alpha",   status: "scheduled" },
  { id: "j2", route_index: 1, customer_name: "Bravo",   status: "scheduled" },
  { id: "j3", route_index: 2, customer_name: "Charlie", status: "scheduled" },
];


/** Thin harness that exposes the hook so tests can drive it like a
 *  real card-list. Renders a NumberOrderInput per job and the
 *  ReorderBanner above them. */
function Harness({ jobs = JOBS, ...opts }) {
  const controller = useNumberedOrder(jobs, {
    autoSave: true, techUserId: "tech-1", date: "2026-03-15", ...opts,
  });
  return (
    <div>
      <ReorderBanner controller={controller} />
      {jobs.map((j) => (
        <div key={j.id} data-testid={`row-${j.id}`}>
          <NumberOrderInput job={j} controller={controller} />
          <span>{j.customer_name}</span>
        </div>
      ))}
    </div>
  );
}


beforeEach(() => {
  _h.post.mockReset();
  _h.post.mockResolvedValue({ ok: true, updated: 3, expected: 3,
                                tech_user_id: "tech-1", date: "2026-03-15" });
});


/* ── Inline behavior ──────────────────────────────────────── */

describe("Numbered-order inline inputs", () => {
  it("renders one input per job, prefilled from route_index+1", () => {
    render(<Harness />);
    expect(screen.getByTestId("route-order-input-j1").value).toBe("1");
    expect(screen.getByTestId("route-order-input-j2").value).toBe("2");
    expect(screen.getByTestId("route-order-input-j3").value).toBe("3");
  });

  it("uses the reorder-num-input class so the browser's spinner arrows are hidden (Option A)", () => {
    render(<Harness />);
    // Every inline number input carries the shared class; the
    // sibling `index.css` rule hides the ▲▼ spinner UI cross-
    // browser via ``::-webkit-*-spin-button`` + Firefox's
    // ``-moz-appearance: textfield``.
    for (const id of ["j1", "j2", "j3"]) {
      const el = screen.getByTestId(`route-order-input-${id}`);
      expect(el.className).toMatch(/reorder-num-input/);
      // Type stays ``number`` (Option A) so the browser-level
      // validation + numeric keypad on mobile stay intact.
      expect(el.getAttribute("type")).toBe("number");
      expect(el.getAttribute("inputmode")).toBe("numeric");
    }
  });

  it("duplicate numbers → red border on both inputs + banner + POST NOT fired", async () => {
    render(<Harness />);
    const i1 = screen.getByTestId("route-order-input-j1");
    const i2 = screen.getByTestId("route-order-input-j2");

    // Change j1 from 1 to 2 → duplicates j2's 2.
    await act(async () => {
      fireEvent.change(i1, { target: { value: "2" } });
      fireEvent.blur(i1);
    });

    expect(i1.getAttribute("aria-invalid")).toBe("true");
    expect(i2.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByTestId("route-order-error-banner").textContent)
      .toMatch(/unique 1–3/);
    expect(_h.post).not.toHaveBeenCalled();
  });

  it("blank value → red border + banner + POST NOT fired", async () => {
    render(<Harness />);
    const i2 = screen.getByTestId("route-order-input-j2");
    await act(async () => {
      fireEvent.change(i2, { target: { value: "" } });
      fireEvent.blur(i2);
    });
    expect(i2.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByTestId("route-order-error-banner").textContent)
      .toMatch(/must have a number 1–3/);
    expect(_h.post).not.toHaveBeenCalled();
  });

  it("out-of-range value → red border + banner + POST NOT fired", async () => {
    render(<Harness />);
    const i3 = screen.getByTestId("route-order-input-j3");
    await act(async () => {
      fireEvent.change(i3, { target: { value: "9" } });
      fireEvent.blur(i3);
    });
    expect(i3.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByTestId("route-order-error-banner").textContent)
      .toMatch(/between 1 and 3/);
    expect(_h.post).not.toHaveBeenCalled();
  });

  it("valid change on blur → POST /jobs/reorder with correctly-ordered job_ids", async () => {
    render(<Harness />);
    const i1 = screen.getByTestId("route-order-input-j1");
    const i3 = screen.getByTestId("route-order-input-j3");

    // Swap j1 ↔ j3 in a single valid mutation.
    await act(async () => {
      fireEvent.change(i1, { target: { value: "3" } });
      fireEvent.change(i3, { target: { value: "1" } });
      fireEvent.blur(i1);   // triggers auto-save (valid at this point)
    });

    await waitFor(() => {
      expect(_h.post).toHaveBeenCalledWith(
        "/jobs/reorder",
        expect.objectContaining({
          ordered_job_ids: ["j3", "j2", "j1"],
          tech_user_id: "tech-1",
          date: "2026-03-15",
        }),
      );
    });
  });

  it("cross-tech safety — controller derives buildOrderedIds only when valid", async () => {
    let currentValid = null;
    let currentIds = null;
    function Probe() {
      const c = useNumberedOrder(JOBS, { autoSave: false });
      currentValid = c.validation.valid;
      currentIds = c.buildOrderedIds();
      const [, setBump] = useState(0);
      return (
        <>
          <NumberOrderInput job={JOBS[0]} controller={c} testId="probe-in-1" />
          <button data-testid="bump" onClick={() => setBump((x) => x + 1)}>bump</button>
        </>
      );
    }
    render(<Probe />);
    // Baseline: prefill is valid, buildOrderedIds returns the array.
    expect(currentValid).toBe(true);
    expect(currentIds).toEqual(["j1", "j2", "j3"]);

    // Introduce a duplicate — buildOrderedIds must go null.
    await act(async () => {
      fireEvent.change(screen.getByTestId("probe-in-1"), { target: { value: "2" } });
      fireEvent.click(screen.getByTestId("bump"));
    });
    expect(currentValid).toBe(false);
    expect(currentIds).toBeNull();
  });
});


/* ── Bulk modal behavior ──────────────────────────────────── */

describe("Bulk Reorder modal", () => {
  it("opens with a row per job, all prefilled from route_index+1", () => {
    render(<BulkReorderModal jobs={JOBS}
                              techUserId="tech-1" date="2026-03-15"
                              onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(screen.getByTestId("bulk-reorder-modal")).toBeInTheDocument();
    expect(screen.getByTestId("bulk-reorder-input-j1").value).toBe("1");
    expect(screen.getByTestId("bulk-reorder-input-j2").value).toBe("2");
    expect(screen.getByTestId("bulk-reorder-input-j3").value).toBe("3");
  });

  it("Save button is disabled while any input is invalid", async () => {
    render(<BulkReorderModal jobs={JOBS}
                              techUserId="tech-1" date="2026-03-15"
                              onClose={vi.fn()} onSaved={vi.fn()} />);
    const i1 = screen.getByTestId("bulk-reorder-input-j1");
    const saveBtn = screen.getByTestId("bulk-reorder-save");
    expect(saveBtn.disabled).toBe(false);

    await act(async () => {
      fireEvent.change(i1, { target: { value: "2" } });  // duplicate
    });
    expect(saveBtn.disabled).toBe(true);
  });

  it("clicking Save POSTs /jobs/reorder with the new order and closes", async () => {
    const onClose = vi.fn();
    const onSaved = vi.fn();
    render(<BulkReorderModal jobs={JOBS}
                              techUserId="tech-1" date="2026-03-15"
                              onClose={onClose} onSaved={onSaved} />);

    const i1 = screen.getByTestId("bulk-reorder-input-j1");
    const i3 = screen.getByTestId("bulk-reorder-input-j3");
    await act(async () => {
      fireEvent.change(i1, { target: { value: "3" } });
      fireEvent.change(i3, { target: { value: "1" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("bulk-reorder-save"));
    });

    await waitFor(() => {
      expect(_h.post).toHaveBeenCalledWith(
        "/jobs/reorder",
        expect.objectContaining({
          ordered_job_ids: ["j3", "j2", "j1"],
          tech_user_id: "tech-1",
          date: "2026-03-15",
        }),
      );
      expect(onSaved).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("Cancel closes without saving", async () => {
    const onClose = vi.fn();
    render(<BulkReorderModal jobs={JOBS}
                              techUserId="tech-1" date="2026-03-15"
                              onClose={onClose} onSaved={vi.fn()} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("bulk-reorder-cancel"));
    });
    expect(onClose).toHaveBeenCalled();
    expect(_h.post).not.toHaveBeenCalled();
  });
});


/* ── DnD-gone regression guard ────────────────────────────── */

describe("DnD affordances are gone (numbered-order pivot)", () => {
  it("ScheduleDayDnDPanel file is no longer present on disk", async () => {
    // We check filesystem presence rather than trying to
    // dynamic-import (which Vite would resolve statically at
    // transform time and error out early).
    // eslint-disable-next-line global-require
    const fs = await import("fs");
    // eslint-disable-next-line global-require
    const path = await import("path");
    const target = path.resolve(
      __dirname, "..", "pages", "schedule", "ScheduleDayDnDPanel.jsx",
    );
    expect(fs.existsSync(target)).toBe(false);
  });
});
