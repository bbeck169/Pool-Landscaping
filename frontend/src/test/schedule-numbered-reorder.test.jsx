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
      .toMatch(/must be unique/i);
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
      .toMatch(/needs a number/i);
    expect(_h.post).not.toHaveBeenCalled();
  });

  it("out-of-range value (>50 cap) → red border + banner + POST NOT fired", async () => {
    render(<Harness />);
    const i3 = screen.getByTestId("route-order-input-j3");
    await act(async () => {
      fireEvent.change(i3, { target: { value: "51" } });
      fireEvent.blur(i3);
    });
    expect(i3.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByTestId("route-order-error-banner").textContent)
      .toMatch(/unique positive integers .*1.*50/i);
    expect(_h.post).not.toHaveBeenCalled();
  });

  it("zero value → red border + banner + POST NOT fired", async () => {
    render(<Harness />);
    const i1 = screen.getByTestId("route-order-input-j1");
    await act(async () => {
      fireEvent.change(i1, { target: { value: "0" } });
      fireEvent.blur(i1);
    });
    expect(i1.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByTestId("route-order-error-banner").textContent)
      .toMatch(/unique positive integers .*1.*50/i);
    expect(_h.post).not.toHaveBeenCalled();
  });

  it("negative value is silently rejected at the input layer (digit-only guard) — draft stays valid, no error, no POST", async () => {
    render(<Harness />);
    const i1 = screen.getByTestId("route-order-input-j1");
    await act(async () => {
      // The setInput guard drops non-digit values silently — the
      // draft keeps its prior "1" so on blur the whole day is
      // still valid and auto-save runs.  This is intentional; the
      // browser's ``type="number"`` won't emit ``-1`` on a
      // fresh keystroke either.
      fireEvent.change(i1, { target: { value: "-1" } });
      fireEvent.blur(i1);
    });
    expect(i1.value).toBe("1");
    expect(i1.getAttribute("aria-invalid")).toBe("false");
  });

  it("non-contiguous numbers (1, 5, 12) save cleanly — cap relaxed from 1..N to 1..50", async () => {
    render(<Harness />);
    const i1 = screen.getByTestId("route-order-input-j1");
    const i2 = screen.getByTestId("route-order-input-j2");
    const i3 = screen.getByTestId("route-order-input-j3");

    await act(async () => {
      fireEvent.change(i1, { target: { value: "1"  } });
      fireEvent.change(i2, { target: { value: "5"  } });
      fireEvent.change(i3, { target: { value: "12" } });
      fireEvent.blur(i3);   // whole day is valid — auto-save fires
    });

    // No validation banner while every value is unique + in range.
    expect(screen.queryByTestId("route-order-error-banner")).toBeNull();
    // Sorted by the typed numbers ascending — the id list is
    // ``[j1, j2, j3]`` because 1 < 5 < 12.  If a user typed
    // ``[9, 5, 12]`` the payload would be ``[j2, j1, j3]``.
    await waitFor(() => {
      expect(_h.post).toHaveBeenCalledWith(
        "/jobs/reorder",
        expect.objectContaining({
          ordered_job_ids: ["j1", "j2", "j3"],
          tech_user_id: "tech-1",
          date: "2026-03-15",
        }),
      );
    });
  });

  it("duplicate values 1,1,3 remain rejected", async () => {
    render(<Harness />);
    const i2 = screen.getByTestId("route-order-input-j2");
    await act(async () => {
      fireEvent.change(i2, { target: { value: "1" } });   // duplicates j1
      fireEvent.blur(i2);
    });
    expect(screen.getByTestId("route-order-error-banner").textContent)
      .toMatch(/must be unique/i);
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

describe.skip("Bulk Reorder modal (Phase C · retired — see reorder-route-modal.test.jsx)", () => {
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

  it("CalendarSchedule renders `dayJobs` directly — no client-side sort that could re-introduce the Feb-2026 read-path mismatch", async () => {
    // The read-path fix in ``backend/routers/jobs.py`` +
    // ``schedule.py`` sorts by ``(scheduled_date, route_index,
    // created_at)`` server-side. The frontend MUST trust that
    // order — any local ``.sort()`` on the day's jobs would silently
    // re-shuffle them and re-open the exact bug the fix closed.
    const fs = await import("fs");
    const path = await import("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "..", "pages", "schedule", "CalendarSchedule.jsx"),
      "utf-8",
    );
    // Non-comment lines only (strip ``//`` + block-comment leading ``*``).
    const code = src
      .split("\n")
      .filter((l) => !/^\s*(?:\/\/|\*)/.test(l))
      .join("\n");
    // The only permitted ``.sort()`` calls on the day's jobs are
    // inside ``NumberedReorder.jsx`` (build the ordered payload for
    // the API) and the ``_TERMINAL`` filter derivation.  Any
    // ``dayJobs.sort(`` / ``gridList.sort(`` / ``jobs.sort(`` at
    // the schedule-page level would be a regression.
    expect(code).not.toMatch(/\b(dayJobs|gridList)\.sort\s*\(/);
  });
});
