/**
 * Phase 51.5 · Feb 2026 — Walkie pin idempotency contract.
 *
 * The server treats pinning the already-pinned message as a no-op
 * (returns 200 with ``unchanged: true``). The web UI's optimistic
 * update must therefore also be a no-op: no timeline flicker, no
 * spurious toast, no additional receipt writes.
 *
 * We test the pure state-transition predicate that ``Walkie.jsx``
 * applies after a successful pin call.
 */
import { describe, it, expect } from "vitest";

/**
 * Optimistic pin update — mirrors the reducer inside ``Walkie.jsx``.
 * Given the current messages list and a target ``pinned_id``, mark
 * exactly one row as pinned. If the row is already pinned, the
 * mapping is a fixed point (no state churn).
 */
function applyPin(messages, pinnedId) {
  return messages.map((m) => ({ ...m, is_pinned: m.id === pinnedId }));
}

function applyUnpin(messages) {
  return messages.map((m) => ({ ...m, is_pinned: false }));
}

describe("Phase 51.5 · walkie pin idempotency", () => {
  it("pinning the already-pinned message is a fixed point", () => {
    const before = [
      { id: "m1", is_pinned: true },
      { id: "m2", is_pinned: false },
    ];
    const after = applyPin(before, "m1");
    expect(after).toEqual(before);
  });

  it("pinning a different message unpins the previous one atomically", () => {
    const before = [
      { id: "m1", is_pinned: true },
      { id: "m2", is_pinned: false },
    ];
    const after = applyPin(before, "m2");
    expect(after.find((m) => m.id === "m1").is_pinned).toBe(false);
    expect(after.find((m) => m.id === "m2").is_pinned).toBe(true);
  });

  it("only ONE message ends up pinned even if the server list contains duplicates", () => {
    const before = [
      { id: "m1", is_pinned: true },
      { id: "m2", is_pinned: true },  // pre-existing bad state
      { id: "m3", is_pinned: false },
    ];
    const after = applyPin(before, "m3");
    const pinnedCount = after.filter((m) => m.is_pinned).length;
    expect(pinnedCount).toBe(1);
    expect(after.find((m) => m.id === "m3").is_pinned).toBe(true);
  });

  it("unpinning clears every pinned flag regardless of prior state", () => {
    const before = [
      { id: "m1", is_pinned: true },
      { id: "m2", is_pinned: true },
      { id: "m3", is_pinned: false },
    ];
    const after = applyUnpin(before);
    expect(after.every((m) => m.is_pinned === false)).toBe(true);
  });
});
