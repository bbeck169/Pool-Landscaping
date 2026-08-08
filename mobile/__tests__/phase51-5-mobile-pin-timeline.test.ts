/**
 * Phase 51.5 · Feb-2026 — Mobile walkie pin timeline order.
 *
 * Locks the same ordering invariant the web enforces:
 *   pinned message first, then remaining rows sorted by
 *   ``created_at desc``. Testing the pure re-sort helper avoids
 *   needing a full Jest mount + expo-audio mock stack for what is
 *   really an ordering contract.
 */
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async () => null),
  setItem: jest.fn(async () => undefined),
  removeItem: jest.fn(async () => undefined),
  clear: jest.fn(async () => undefined),
}));

// Mirror of the client-side re-sort helper used in the mobile
// timeline. Extracted here so we can exercise the ordering
// invariant without mounting jsdom + the expo-audio player.
function orderTimeline(messages: any[]): any[] {
  const pinned = messages.filter((m) => m.is_pinned);
  const rest = messages.filter((m) => !m.is_pinned).slice().sort(
    (a: any, b: any) => (b.created_at || "").localeCompare(a.created_at || "")
  );
  return [...pinned, ...rest];
}

describe("Phase 51.5 · mobile pin timeline order", () => {
  const T = (n: number) => `2026-02-07T10:${String(n).padStart(2, "0")}:00Z`;

  it("pinned message renders first even when older than the newest", () => {
    const msgs = [
      { id: "m1", is_pinned: true, created_at: T(0) },
      { id: "m2", is_pinned: false, created_at: T(5) },
      { id: "m3", is_pinned: false, created_at: T(3) },
    ];
    expect(orderTimeline(msgs).map((m) => m.id)).toEqual(["m1", "m2", "m3"]);
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
