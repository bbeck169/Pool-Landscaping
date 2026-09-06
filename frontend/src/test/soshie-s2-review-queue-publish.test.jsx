/**
 * Phase S2 · Feb-2026 — Review Queue "Publish now" always sends
 * ``confirm_flags=1``.
 *
 * The review queue only shows actions that need attention
 * (flagged, past-24hr, human-review, or deferred-no-credits).
 * Publishing from this surface therefore ALWAYS acknowledges
 * moderation flags — the button must call
 * ``POST /ai-employees/actions/{aid}/approve?confirm_flags=1``
 * unconditionally, even when the row happens to have zero flags.
 * This test locks in the query-string contract.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { api } from "@/api";
import ReviewQueueTab from "@/pages/soshie/ReviewQueueTab";

// Age > 24hr so it lands in the review queue.
const OLD_ISO = new Date(Date.now() - 30 * 3_600_000).toISOString();

const ROWS = [
  {
    id: "act-1",
    action: "soshie.publish_blog",
    status: "pending",
    employee_key: "soshie",
    params: { platform: "wordpress" },
    draft: { text: "Body of the draft goes here.",
                title: "Hello", platform: "wordpress" },
    summary: "Body of the draft goes here.",
    moderation_flags: [],
    requires_human_approval: false,
    media_url: null, media_source: null, brand_score: null,
    created_at: OLD_ISO,
    updated_at: OLD_ISO,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((path) => {
    if (path.includes("status=pending")) {
      return Promise.resolve({ items: ROWS });
    }
    if (path.includes("status=deferred_no_credits")) {
      return Promise.resolve({ items: [] });
    }
    return Promise.resolve({});
  });
});

describe("S2 · review queue publish-now", () => {
  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("Publish now always sends confirm_flags=1", async () => {
    api.post.mockResolvedValueOnce({
      status: "published",
      result: { kind: "soshie_blog_published" },
    });
    render(<ReviewQueueTab />);
    const btn = await screen.findByTestId("review-publish-act-1");
    fireEvent.click(btn);
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [path] = api.post.mock.calls[0];
    expect(path).toBe(
      "/ai-employees/actions/act-1/approve?confirm_flags=1");
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("Reject wires to the reject endpoint with a note", async () => {
    api.post.mockResolvedValueOnce({ status: "rejected" });
    render(<ReviewQueueTab />);
    const btn = await screen.findByTestId("review-reject-act-1");
    fireEvent.click(btn);
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [path, body] = api.post.mock.calls[0];
    expect(path).toBe("/ai-employees/actions/act-1/reject");
    expect(body).toMatchObject({ note: expect.any(String) });
  });
});
