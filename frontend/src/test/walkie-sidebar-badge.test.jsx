/**
 * Phase 51b · Walkie-Talkie sidebar badge aggregation.
 *
 * The sidebar badge sums unread receipts across every visible
 * channel. Zero → hidden. This test locks the maths in place so a
 * future refactor doesn't accidentally start counting listened
 * messages or double-count directs.
 */
import { describe, it, expect } from "vitest";
import { totalUnread, sortChannels } from "@/pages/walkie/walkie-helpers";

describe("totalUnread — walkie sidebar badge", () => {
  it("returns 0 for an empty list", () => {
    expect(totalUnread([])).toBe(0);
    expect(totalUnread(undefined)).toBe(0);
    expect(totalUnread(null)).toBe(0);
  });

  it("sums unread_count across mixed channel kinds", () => {
    const chs = [
      { id: "1", kind: "all_hands", unread_count: 3 },
      { id: "2", kind: "department", department: "pool", unread_count: 1 },
      { id: "3", kind: "direct", unread_count: 5 },
    ];
    expect(totalUnread(chs)).toBe(9);
  });

  it("treats missing/null unread_count as zero", () => {
    const chs = [
      { id: "1", kind: "all_hands" },
      { id: "2", kind: "direct", unread_count: null },
      { id: "3", kind: "direct", unread_count: 4 },
    ];
    expect(totalUnread(chs)).toBe(4);
  });

  it("coerces string counts (defensive vs. backend shape drift)", () => {
    const chs = [
      { id: "1", kind: "all_hands", unread_count: "2" },
      { id: "2", kind: "direct", unread_count: "3" },
    ];
    expect(totalUnread(chs)).toBe(5);
  });
});

describe("sortChannels — left rail ordering", () => {
  it("puts all_hands first, then departments (alpha), then directs newest-first", () => {
    const chs = [
      { id: "d2", kind: "direct", created_at: "2026-02-05T10:00:00Z" },
      { id: "dep_pool", kind: "department", department: "pool" },
      { id: "d1", kind: "direct", created_at: "2026-02-06T10:00:00Z" },
      { id: "ah", kind: "all_hands" },
      { id: "dep_land", kind: "department", department: "landscape" },
    ];
    const sorted = sortChannels(chs);
    expect(sorted.map((c) => c.id)).toEqual([
      "ah", "dep_land", "dep_pool", "d1", "d2",
    ]);
  });
});
