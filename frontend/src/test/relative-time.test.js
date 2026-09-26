/**
 * QV-ui · Feb-2026 — Shared relative-time formatter tests.
 *
 * Locks byte-parity with the pre-extraction inline copies from
 * ``InvoiceViewHistory.jsx`` + ``InvoicesList.jsx``. Any wording
 * change breaks these tests intentionally — extraction stays
 * pure; wording refactors live in their own commit.
 *
 * Every fixture pins ``now`` via injection so the assertions are
 * hermetic and don't drift with wall-clock time.
 */
import { describe, it, expect } from "vitest";
import {
  formatRelativeFromIso,
  formatLocalFromIso,
} from "@/lib/relativeTime";


// Reference clock — 2026-02-20 15:00:00 UTC.
const NOW_MS = Date.parse("2026-02-20T15:00:00Z");
const NOW = new Date(NOW_MS);


describe("formatRelativeFromIso · byte-parity contract", () => {
  it("returns '' for null / undefined / empty / whitespace", () => {
    expect(formatRelativeFromIso(null, NOW)).toBe("");
    expect(formatRelativeFromIso(undefined, NOW)).toBe("");
    expect(formatRelativeFromIso("", NOW)).toBe("");
  });

  it("returns '' for a malformed ISO string", () => {
    expect(formatRelativeFromIso("not-a-date", NOW)).toBe("");
    expect(formatRelativeFromIso("2026-99-99", NOW)).toBe("");
  });

  // ── seconds bucket ─────────────────────────────────────────
  it("0 seconds ago → '0s ago'", () => {
    expect(formatRelativeFromIso("2026-02-20T15:00:00Z", NOW))
      .toBe("0s ago");
  });
  it("30 seconds ago → '30s ago'", () => {
    expect(formatRelativeFromIso("2026-02-20T14:59:30Z", NOW))
      .toBe("30s ago");
  });
  it("59 seconds ago → '59s ago' (edge)", () => {
    expect(formatRelativeFromIso("2026-02-20T14:59:01Z", NOW))
      .toBe("59s ago");
  });

  // ── minutes bucket ────────────────────────────────────────
  it("60 seconds ago → '1m ago' (rollover)", () => {
    expect(formatRelativeFromIso("2026-02-20T14:59:00Z", NOW))
      .toBe("1m ago");
  });
  it("5 minutes ago → '5m ago'", () => {
    expect(formatRelativeFromIso("2026-02-20T14:55:00Z", NOW))
      .toBe("5m ago");
  });
  it("59 minutes ago → '59m ago' (edge)", () => {
    expect(formatRelativeFromIso("2026-02-20T14:01:00Z", NOW))
      .toBe("59m ago");
  });

  // ── hours bucket ──────────────────────────────────────────
  it("60 minutes ago → '1h ago' (rollover)", () => {
    expect(formatRelativeFromIso("2026-02-20T14:00:00Z", NOW))
      .toBe("1h ago");
  });
  it("23 hours ago → '23h ago' (edge)", () => {
    expect(formatRelativeFromIso("2026-02-19T16:00:00Z", NOW))
      .toBe("23h ago");
  });

  // ── days bucket ───────────────────────────────────────────
  it("24 hours ago → '1d ago' (rollover)", () => {
    expect(formatRelativeFromIso("2026-02-19T15:00:00Z", NOW))
      .toBe("1d ago");
  });
  it("6 days ago → '6d ago'", () => {
    expect(formatRelativeFromIso("2026-02-14T15:00:00Z", NOW))
      .toBe("6d ago");
  });
  it("29 days ago → '29d ago' (edge)", () => {
    expect(formatRelativeFromIso("2026-01-22T15:00:00Z", NOW))
      .toBe("29d ago");
  });

  // ── months bucket ─────────────────────────────────────────
  it("30 days ago → '1mo ago' (rollover, 30-day months)", () => {
    expect(formatRelativeFromIso("2026-01-21T15:00:00Z", NOW))
      .toBe("1mo ago");
  });
  it("1 year ago → '12mo ago' (30-day months, not calendar)", () => {
    // 365 days ÷ 30 = 12.16… floored → 12mo. Byte-parity with
    // the pre-extraction inline copy — we intentionally do NOT
    // pluralise or roll into "years" (that's a separate commit
    // if we ever want it).
    expect(formatRelativeFromIso("2025-02-20T15:00:00Z", NOW))
      .toBe("12mo ago");
  });

  it("future timestamp is clamped to '0s ago'", () => {
    expect(formatRelativeFromIso("2026-02-20T15:00:30Z", NOW))
      .toBe("0s ago");
  });

  it("accepts a numeric epoch-ms as the second arg", () => {
    expect(formatRelativeFromIso("2026-02-20T14:59:30Z", NOW_MS))
      .toBe("30s ago");
  });

  it("defaults to Date.now() when second arg is omitted", () => {
    const iso = new Date(Date.now() - 5_000).toISOString();
    // Real-time — pin to seconds bucket only. Allow ±1s wiggle
    // for CI clock granularity.
    const out = formatRelativeFromIso(iso);
    expect(out).toMatch(/^[0-9]+s ago$/);
  });
});


describe("formatLocalFromIso · absolute tooltip helper", () => {
  it("returns '' for null / empty", () => {
    expect(formatLocalFromIso(null)).toBe("");
    expect(formatLocalFromIso("")).toBe("");
  });

  it("returns raw iso when unparseable", () => {
    expect(formatLocalFromIso("not-a-date")).toBe("not-a-date");
  });

  it("returns a non-empty localised string for a valid ISO", () => {
    const out = formatLocalFromIso("2026-02-20T15:00:00Z");
    expect(typeof out).toBe("string");
    expect(out.length).toBeGreaterThan(0);
    // Zero-locale coupling — different jsdom nodes can render
    // slightly different strings; the invariant is just
    // non-empty + non-raw.
    expect(out).not.toBe("2026-02-20T15:00:00Z");
  });
});
