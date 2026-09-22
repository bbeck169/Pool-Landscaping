/**
 * Phase P25 · Feb-2026 — NumberedReorder draft-preserve on server sync.
 *
 * Pre-P25 the ``useNumberedOrder`` hook's sync-effect unconditionally
 * re-hydrated every row's draft from the server-pushed ``route_index``
 * (or the ``initialOrder`` argument). That clobbered the user's
 * in-flight edit: the user would type ``7`` into row 3, the parent's
 * optimistic reorder response would re-fire the memo, and the input
 * would snap back to the server's stale ``3``.
 *
 * Fix rule (from the phase spec):
 *   - Preserve drafts ONLY for rows whose input is currently focused
 *     (in ``typingIds``).
 *   - Rows outside the typing set re-hydrate from the fresh server
 *     data on every push.
 *   - Blur eviction from ``typingIds`` is debounced ~300 ms so an
 *     IME recomposition (blur → immediate focus) doesn't yank the
 *     protection mid-composition.
 *
 * These specs exercise the hook directly + the ``NumberOrderInput``
 * primitive that wires focus/blur into the ``notifyFocus`` /
 * ``notifyBlur`` transitions. Renderer-only, no real API calls.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";


/* ── Hoisted mocks (mirrors schedule-numbered-reorder.test.jsx) ─ */
const _h = vi.hoisted(() => ({ post: vi.fn() }));

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
} from "@/pages/schedule/NumberedReorder";


/* ── Test harness ─────────────────────────────────────────────
 * Renders 3 `<NumberOrderInput>` primitives backed by a shared
 * controller. The parent owns the ``jobs`` array so the test can
 * push "fresh from server" values by swapping ``route_index``. */
function _makeJobs(indexes) {
  return indexes.map((rix, i) => ({
    id: `j${i + 1}`,
    customer_name: `Cust ${i + 1}`,
    route_index: rix,
  }));
}

// Real timers throughout — the P25 debounce is 300 ms; a real wait
// costs ~400 ms per test and avoids the ``vi.useFakeTimers`` + React
// concurrent-scheduler interaction that hangs the worker.
// ``Harness._ref`` is a plain object (not a React ref) — we assign
// ``current`` from inside the Harness on every render so tests can
// call ``pushServer`` from outside without ``useImperativeHandle`` /
// ``forwardRef`` gymnastics. Reset in ``beforeEach`` so a leaked
// reference from a prior test can't drive the current render.
function Harness({ initialIndexes = [0, 1, 2] }) {
  const [jobs, setJobs] = React.useState(_makeJobs(initialIndexes));
  const controller = useNumberedOrder(jobs, { autoSave: false });
  Harness._ref.current = {
    controller,
    pushServer: (newIndexes) => setJobs(_makeJobs(newIndexes)),
  };
  return (
    <div>
      {jobs.map((j) => (
        <NumberOrderInput
          key={j.id}
          job={j}
          controller={controller}
          testId={`input-${j.id}`}
        />
      ))}
    </div>
  );
}
Harness._ref = { current: null };


beforeEach(() => {
  _h.post.mockReset();
  Harness._ref.current = null;
});

// Real timers throughout — the P25 debounce is 300 ms; a real wait
// costs ~400 ms per test and avoids the ``vi.useFakeTimers`` + React
// concurrent-scheduler interaction that hangs the worker.
async function _flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function _wait(ms) {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}


describe("P25 · NumberedReorder draft-preserve on server sync", () => {
  it("server push updates ALL non-focused rows to the new positions", async () => {
    render(<Harness initialIndexes={[0, 1, 2]} />);

    // Initial drafts: "1", "2", "3"
    expect(screen.getByTestId("input-j1").value).toBe("1");
    expect(screen.getByTestId("input-j2").value).toBe("2");
    expect(screen.getByTestId("input-j3").value).toBe("3");

    // Server pushes a reversed order.
    await act(async () => {
      Harness._ref.current.pushServer([2, 1, 0]);
    });
    await _flush();

    // All three rows re-hydrate from the new server values.
    expect(screen.getByTestId("input-j1").value).toBe("3");
    expect(screen.getByTestId("input-j2").value).toBe("2");
    expect(screen.getByTestId("input-j3").value).toBe("1");
  });

  it("focused row keeps its typed draft on server push; other rows update", async () => {
    render(<Harness initialIndexes={[0, 1, 2]} />);
    const input3 = screen.getByTestId("input-j3");

    // User focuses row 3 and types "7".
    await act(async () => { fireEvent.focus(input3); });
    await act(async () => {
      fireEvent.change(input3, { target: { value: "7" } });
    });
    expect(input3.value).toBe("7");

    // Server push arrives — new positions [10, 20, 30] (i.e.
    // ``route_index`` 9/19/29 → drafts would be 10/20/30).
    await act(async () => {
      Harness._ref.current.pushServer([9, 19, 29]);
    });
    await _flush();

    // Non-focused rows re-hydrate.
    expect(screen.getByTestId("input-j1").value).toBe("10");
    expect(screen.getByTestId("input-j2").value).toBe("20");
    // Focused row keeps the mid-edit "7".
    expect(input3.value).toBe("7");
  });

  it("row that blurred >300ms ago accepts the next server push", async () => {
    render(<Harness initialIndexes={[0, 1, 2]} />);
    const input3 = screen.getByTestId("input-j3");

    await act(async () => { fireEvent.focus(input3); });
    await act(async () => {
      fireEvent.change(input3, { target: { value: "7" } });
    });
    // Blur (schedules the 300ms eviction from typingIds).
    await act(async () => { fireEvent.blur(input3); });
    // Wait PAST the grace window.
    await _wait(400);

    // Server push — row 3 is no longer in the typing set, so it
    // should accept the new value.
    await act(async () => {
      Harness._ref.current.pushServer([0, 1, 8]);
    });
    await _flush();
    expect(input3.value).toBe("9");
  });

  it("IME/quick-refocus race: focus → immediate server push → row still protected", async () => {
    render(<Harness initialIndexes={[0, 1, 2]} />);
    const input2 = screen.getByTestId("input-j2");

    // User focuses row 2, types "42".
    await act(async () => { fireEvent.focus(input2); });
    await act(async () => {
      fireEvent.change(input2, { target: { value: "42" } });
    });

    // Immediate server push while row 2 is still focused (no blur).
    await act(async () => {
      Harness._ref.current.pushServer([5, 6, 7]);
    });
    await _flush();
    expect(input2.value).toBe("42");   // preserved

    // IME edge: user blurs, then INSIDE the grace window (< 300ms)
    // refocuses. The blur-eviction timer must be cancelled so a
    // server push that lands DURING composition still preserves
    // the draft.
    await act(async () => { fireEvent.blur(input2); });
    await _wait(100);
    await act(async () => { fireEvent.focus(input2); });
    await _wait(500);   // past 300ms — but focus cancelled the timer
    // Change to a new value during composition.
    await act(async () => {
      fireEvent.change(input2, { target: { value: "99" } });
    });
    // Server push arrives mid-composition — protected.
    await act(async () => {
      Harness._ref.current.pushServer([10, 11, 12]);
    });
    await _flush();
    expect(input2.value).toBe("99");
  });

  it("initial draft state seeds from server route_index — pre-P25 baseline", async () => {
    // Guardrail: the fix must not have accidentally broken the
    // initial hydration when there's no user interaction.
    render(<Harness initialIndexes={[4, 5, 6]} />);
    expect(screen.getByTestId("input-j1").value).toBe("5");
    expect(screen.getByTestId("input-j2").value).toBe("6");
    expect(screen.getByTestId("input-j3").value).toBe("7");
  });

  it("controller exposes notifyFocus/notifyBlur/typingIds for external number inputs", () => {
    // Guardrail: consumer components that build their own number
    // inputs (not the shipped ``NumberOrderInput``) must still be
    // able to opt into the P25 protection surface.
    let ctrl = null;
    // ``jobs`` MUST be stable-referenced across renders or the
    // hook's sync-effect + validation memo would thrash and stall
    // the vitest worker (the pre-P25 fix would re-hydrate every
    // render, which cascaded into a render loop under React 18
    // concurrent mode).
    const _jobs = _makeJobs([0, 1]);
    function Probe() {
      ctrl = useNumberedOrder(_jobs, { autoSave: false });
      return null;
    }
    render(<Probe />);
    expect(typeof ctrl.notifyFocus).toBe("function");
    expect(typeof ctrl.notifyBlur).toBe("function");
    expect(ctrl.typingIds instanceof Set).toBe(true);
    expect(ctrl.typingIds.size).toBe(0);
  });
});
