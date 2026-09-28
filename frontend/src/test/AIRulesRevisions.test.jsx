/**
 * MTH-B · Feb-2026 — Revisions tab tests.
 *
 * Locks:
 *   1. Fetches ``GET /api/tenant-ai-rules/revisions?limit=25`` on mount.
 *   2. Renders one row per revision.
 *   3. Revert flow: opens modal, requires 8-char reason, posts
 *      ``/api/tenant-ai-rules/revert/{n}`` with reason.
 *   4. categoriesChangedBetween diffs two rule payloads.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: { put: vi.fn(), post: vi.fn(), get: vi.fn() },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import RevisionsTab, {
  categoriesChangedBetween,
} from "@/components/ai-rules/RevisionsTab";

const REVS = [
  {
    revision_number: 3,
    last_updated_at: "2026-02-03T10:00:00Z",
    last_updated_by_name: "admin@ex.com",
    last_update_reason: "escalation change",
    rules: {
      tone_voice: { style: "friendly", custom_directive: "" },
      escalation_rules: [{ keyword: "refund", is_regex: false, target_role: "admin", sla_minutes: 5, notify_channel: "email" }],
    },
  },
  {
    revision_number: 2,
    last_updated_at: "2026-02-02T10:00:00Z",
    last_updated_by_name: "admin@ex.com",
    last_update_reason: "tone flip",
    rules: {
      tone_voice: { style: "formal", custom_directive: "" },
      escalation_rules: [],
    },
  },
  {
    revision_number: 1,
    last_updated_at: "2026-02-01T10:00:00Z",
    last_updated_by_name: "seed",
    last_update_reason: "initial",
    rules: { tone_voice: { style: "friendly", custom_directive: "" } },
  },
];

describe("MTH-B · RevisionsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.get.mockImplementation((p) => {
      if (p.startsWith("/tenant-ai-rules/revisions"))
        return Promise.resolve({ count: REVS.length, revisions: REVS });
      return Promise.reject(new Error("not-mocked"));
    });
    _apiMock.post.mockResolvedValue({ ok: true, revision_number: 4 });
  });

  it("fetches on mount + renders one row per revision", async () => {
    render(<RevisionsTab />);
    await waitFor(() =>
      expect(_apiMock.get).toHaveBeenCalledWith(
        "/tenant-ai-rules/revisions?limit=25",
      ),
    );
    expect(screen.getByTestId("ai-rules-revision-row-3")).toBeInTheDocument();
    expect(screen.getByTestId("ai-rules-revision-row-2")).toBeInTheDocument();
    expect(screen.getByTestId("ai-rules-revision-row-1")).toBeInTheDocument();
  });

  it("revert flow POSTs /tenant-ai-rules/revert/{n} with reason", async () => {
    render(<RevisionsTab />);
    await waitFor(() =>
      expect(screen.getByTestId("ai-rules-revision-row-2")).toBeInTheDocument(),
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-revision-row-2-revert"),
    );
    fireEvent.change(
      screen.getByTestId("ai-rules-revert-reason-input"),
      { target: { value: "prod rollback" } },
    );
    fireEvent.click(screen.getByTestId("ai-rules-revert-reason-confirm"));
    await waitFor(() => {
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/tenant-ai-rules/revert/2",
        { reason: "prod rollback" },
      );
    });
  });

  it("categoriesChangedBetween diffs two revision payloads", () => {
    const changed = categoriesChangedBetween(REVS[0], REVS[1]);
    // tone_voice differs (friendly vs formal); escalation_rules differs
    // ([one rule] vs []).
    expect(changed.sort()).toEqual(
      ["escalation_rules", "tone_voice"].sort(),
    );
  });
});
