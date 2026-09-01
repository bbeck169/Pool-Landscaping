/**
 * Phase H5.5 · Feb-2026 — Review Queue Manual-Only affordances.
 *
 * Verifies the ReviewQueueTab renders "Copy to clipboard" +
 * "Mark as posted" buttons for rows with ``status ===
 * "awaiting_manual"``, and that:
 *   * Copy fires ``navigator.clipboard.writeText`` with
 *     ``<draft.text>\n\n<media_url>`` when a media URL is present.
 *   * Mark-Posted fires ``POST /soshie/moderation/{id}/mark-posted``
 *     and disables itself after the row flips.
 */
import React from "react";
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


const MANUAL_ROW = {
  id: "act-manual-1",
  employee_key: "soshie",
  action: "soshie.draft_post",
  status: "awaiting_manual",
  manual_only_platform: "facebook",
  created_at: new Date().toISOString(),
  draft: {
    platform: "facebook",
    text: "This is the full manual-only draft body that must survive intact through the clipboard copy path.",
  },
  media_url: "https://cdn.example.com/img/hero.jpg",
  moderation_flags: [],
  requires_human_approval: false,
};


beforeEach(() => {
  vi.clearAllMocks();
  // Route the three review-queue fetches: only the awaiting_manual
  // one returns our seeded row.
  api.get.mockImplementation((path) => {
    if (path.includes("status=awaiting_manual")) {
      return Promise.resolve({ items: [MANUAL_ROW] });
    }
    return Promise.resolve({ items: [] });
  });
  // Stub the clipboard API — jsdom does not provide one by default.
  const writeText = vi.fn().mockResolvedValue();
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText }, writable: true, configurable: true,
  });
});


describe("H5.5 · ReviewQueueTab · Manual Only affordances", () => {
  it("renders the row with Copy + Mark Posted (no Publish now)", async () => {
    render(<ReviewQueueTab />);
    await waitFor(() =>
      expect(screen.getByTestId(`review-row-${MANUAL_ROW.id}`))
        .toBeInTheDocument(),
    );
    expect(
      screen.getByTestId(`review-copy-${MANUAL_ROW.id}`),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId(`review-mark-posted-${MANUAL_ROW.id}`),
    ).toBeInTheDocument();
    // Publish button IS NOT rendered — that's the wire path.
    expect(
      screen.queryByTestId(`review-publish-${MANUAL_ROW.id}`),
    ).toBeNull();
  });

  it("Copy button calls clipboard.writeText with text + media URL",
     async () => {
    render(<ReviewQueueTab />);
    const copyBtn = await screen.findByTestId(
      `review-copy-${MANUAL_ROW.id}`);
    fireEvent.click(copyBtn);
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalled(),
    );
    const arg = navigator.clipboard.writeText.mock.calls[0][0];
    // Full draft text (NOT the 180-char preview).
    expect(arg).toContain(MANUAL_ROW.draft.text);
    // And media URL appended on a separate line.
    expect(arg).toContain(MANUAL_ROW.media_url);
    // Two-newline separator between the two.
    expect(arg).toContain(`${MANUAL_ROW.draft.text}\n\n${MANUAL_ROW.media_url}`);
  });

  it("Mark Posted fires POST /soshie/moderation/{id}/mark-posted",
     async () => {
    api.post.mockResolvedValue({
      ok: true, post_id: MANUAL_ROW.id,
      new_status: "published_manual",
      already_posted: false,
    });
    // Second load-after-onDone returns no rows so the button never
    // re-renders from state.
    api.get.mockImplementation(() => Promise.resolve({ items: [] }));
    // Prime the initial render.
    api.get.mockImplementationOnce((path) => {
      if (path.includes("status=awaiting_manual")) {
        return Promise.resolve({ items: [MANUAL_ROW] });
      }
      return Promise.resolve({ items: [] });
    });
    api.get.mockImplementationOnce(() => Promise.resolve({ items: [] }));
    api.get.mockImplementationOnce((path) => {
      if (path.includes("status=awaiting_manual")) {
        return Promise.resolve({ items: [MANUAL_ROW] });
      }
      return Promise.resolve({ items: [] });
    });
    render(<ReviewQueueTab />);
    const btn = await screen.findByTestId(
      `review-mark-posted-${MANUAL_ROW.id}`);
    fireEvent.click(btn);
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [url, body] = api.post.mock.calls[0];
    expect(url).toBe(`/soshie/moderation/${MANUAL_ROW.id}/mark-posted`);
    // Body is an empty object per the endpoint contract.
    expect(body).toEqual({});
  });

  it("Mark Posted button is disabled when the row is already posted",
     async () => {
    const alreadyPostedRow = {
      ...MANUAL_ROW,
      status: "published_manual",
      manual_posted_at: new Date().toISOString(),
    };
    api.get.mockImplementation((path) => {
      // Return the published_manual row via the awaiting_manual
      // channel so it renders through the same path (the tile still
      // shows it briefly for the operator's confirmation).
      if (path.includes("status=awaiting_manual")) {
        return Promise.resolve({ items: [alreadyPostedRow] });
      }
      return Promise.resolve({ items: [] });
    });
    render(<ReviewQueueTab />);
    const btn = await screen.findByTestId(
      `review-mark-posted-${MANUAL_ROW.id}`);
    // Button is disabled + text is "Posted".
    expect(btn.hasAttribute("disabled")).toBe(true);
    expect(btn.textContent).toMatch(/posted/i);
  });
});
