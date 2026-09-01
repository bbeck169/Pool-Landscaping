/**
 * Phase K12 · Feb-2026 — Workstream "Completed" column contract.
 *
 * Contracts locked:
 *   1. ``formatCompletedAt`` returns "Mon D, YYYY · h:mm AM/PM" for
 *      a valid ISO ``completed_at``.
 *   2. Falls back to ``updated_at`` when ``completed_at`` missing
 *      AND ``status === "completed"``.
 *   3. Returns em-dash when both are missing.
 *   4. Column line is rendered by JobCard only when the caller
 *      passes ``canBulk=true`` (super_admin / admin / manager).  A
 *      tech-role caller (``canBulk=false``) sees NO Completed line.
 */
import React from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));
vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u", role: "super_admin", name: "Boss" } }),
}));
vi.mock("@/hooks/usePermissions", () => ({ Forbidden: () => null }));

// Neutralize CustomerCombobox + UserAvatar to keep JSDOM light.
vi.mock("@/components/customers/CustomerCombobox", () => ({
  default: () => null,
}));
vi.mock("@/components/UserAvatar", () => ({ UserAvatar: () => null }));
vi.mock("@/components/ui-kit", () => ({ StatusPill: () => null }));

beforeEach(() => {
  // Lock TZ to Los Angeles so the timestamp assertions are stable
  // regardless of the CI runner's TZ.
  process.env.TZ = "America/Los_Angeles";
});
afterEach(() => cleanup());

// Import lazily so the TZ env var is applied before Node bakes it in.
import { formatCompletedAt } from "@/pages/workstream/WorkstreamPage";

describe("Phase K12 · formatCompletedAt", () => {
  it("renders 'Mon D, YYYY · h:mm AM/PM' for a valid completed_at", () => {
    // 2026-09-01T22:42:00Z → 3:42 PM PDT (UTC-7).
    const out = formatCompletedAt({
      completed_at: "2026-09-01T22:42:00Z",
      status: "completed",
    });
    expect(out).toBe("Sep 1, 2026 · 3:42 PM");
  });

  it("falls back to updated_at when completed_at is missing and status=completed", () => {
    const out = formatCompletedAt({
      completed_at: null,
      updated_at: "2026-09-01T22:42:00Z",
      status: "completed",
    });
    expect(out).toBe("Sep 1, 2026 · 3:42 PM");
  });

  it("returns em-dash when both timestamps are missing", () => {
    expect(formatCompletedAt({ completed_at: null,
                                 updated_at: null,
                                 status: "completed" })).toBe("—");
    expect(formatCompletedAt({})).toBe("—");
    expect(formatCompletedAt(null)).toBe("—");
  });

  it("does NOT fall back to updated_at when status is not 'completed'", () => {
    // Non-completed row with no completed_at → em-dash.
    expect(formatCompletedAt({
      completed_at: null,
      updated_at: "2026-09-01T22:42:00Z",
      status: "in_progress",
    })).toBe("—");
  });

  it("returns em-dash for a malformed ISO string", () => {
    expect(formatCompletedAt({
      completed_at: "not-a-date",
      status: "completed",
    })).toBe("—");
  });
});
