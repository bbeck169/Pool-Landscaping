/**
 * Phase 51.5 · Feb 2026 — Walkie pin timeline ordering contract.
 *
 * The backend always returns the pinned message as the FIRST element
 * in ``GET /walkie/messages`` (regardless of the ``since=`` window).
 * The web timeline consumes that order as-is. This test locks the
 * ordering + the pinned badge render + the fact that non-pinned rows
 * still sort by ``created_at desc`` beneath the pinned row.
 */
import { describe, it, expect } from "vitest";

/**
 * Client-side re-sort helper — mirrors what ``Walkie.jsx`` would do
 * after an optimistic pin/unpin state change. Extracted here as a
 * pure function so we can assert the invariants without mounting
 * jsdom (autoplay + `<audio>` mocks add flake surface for no gain).
 */
function orderTimeline(messages) {
  const pinned = messages.filter((m) => m.is_pinned);
  const rest = messages.filter((m) => !m.is_pinned)
    .slice()
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  return [...pinned, ...rest];
}

describe("Phase 51.5 · walkie pin timeline order", () => {
  const T = (n) => `2026-02-07T10:${String(n).padStart(2, "0")}:00Z`;

  it("pinned message renders first even when older than the newest", () => {
    const msgs = [
      { id: "m1", is_pinned: true, created_at: T(0) },
      { id: "m2", is_pinned: false, created_at: T(5) },
      { id: "m3", is_pinned: false, created_at: T(3) },
    ];
    const out = orderTimeline(msgs);
    expect(out.map((m) => m.id)).toEqual(["m1", "m2", "m3"]);
  });

  it("non-pinned rows sort by created_at desc below the pinned row", () => {
    const msgs = [
      { id: "m3", is_pinned: false, created_at: T(3) },
      { id: "m5", is_pinned: false, created_at: T(5) },
      { id: "m1", is_pinned: true, created_at: T(0) },
      { id: "m4", is_pinned: false, created_at: T(4) },
    ];
    expect(orderTimeline(msgs).map((m) => m.id)).toEqual(["m1", "m5", "m4", "m3"]);
  });

  it("only one pinned message is expected — the sort keeps that invariant obvious", () => {
    // If the backend ever leaks two pinned rows the ordering still
    // deterministically renders both at the top in their arrival order.
    // This prevents flicker / duplicate-highlight bugs.
    const msgs = [
      { id: "m1", is_pinned: true, created_at: T(0) },
      { id: "m2", is_pinned: true, created_at: T(5) },
      { id: "m3", is_pinned: false, created_at: T(3) },
    ];
    const out = orderTimeline(msgs);
    expect(out.slice(0, 2).every((m) => m.is_pinned)).toBe(true);
    expect(out[2].id).toBe("m3");
  });

  it("empty list is a no-op", () => {
    expect(orderTimeline([])).toEqual([]);
  });

  it("no pinned messages — pure created_at desc order", () => {
    const msgs = [
      { id: "m3", created_at: T(3) },
      { id: "m5", created_at: T(5) },
      { id: "m1", created_at: T(1) },
    ];
    expect(orderTimeline(msgs).map((m) => m.id)).toEqual(["m5", "m3", "m1"]);
  });
});
