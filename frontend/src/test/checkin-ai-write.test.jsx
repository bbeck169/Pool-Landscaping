/**
 * Feb-2026 · Phase — AI check-in description button ("✨ AI Write").
 *
 * Three cases:
 *   1. Click AI Write → posts to /checkins/{id}/ai-description,
 *      prefills the description textarea, button flips to "Undo AI".
 *   2. Undo AI restores pre-AI content.
 *   3. 429 rate-limit response fires the correct toast copy with
 *      minutes derived from ``retry_after_seconds``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _row = {
  id: "chk-ai-1",
  tenant_id: "T",
  state: "pending_review",
  service_name: "Weekly Pool",
  service_category: "pool_service",
  description: "hand-written by tech",
  photos: [],
  tags: [],
  submitted_at: "2026-02-14T09:00:00Z",
  raw_address: { street: "1 Main St", city: "Peoria", state: "AZ" },
};

let _writeResponse = { description: "AI-generated visit description.",
                        model: "gpt-4o",
                        generated_at: "2026-02-14T10:00:00Z" };
let _writeShouldReject = null; // when set, api.post throws this err

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/admin/moderation/public-checkins?")) {
        return { items: [_row], total: 1, limit: 200, offset: 0 };
      }
      if (path.startsWith("/admin/moderation/public-checkins/")) {
        return _row;
      }
      return {};
    }),
    post: vi.fn(async (path) => {
      if (/\/checkins\/[^/]+\/ai-description$/.test(path)) {
        if (_writeShouldReject) {
          throw _writeShouldReject;
        }
        return _writeResponse;
      }
      if (path === "/checkins/rewrite-description") {
        return { rewritten: "Polished description." };
      }
      return {};
    }),
    patch: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import ModerationCheckinsPage
  from "@/pages/admin/ModerationCheckinsPage";
import { api } from "@/api";
import { toast } from "sonner";

describe("ModerationCheckinsPage · AI Write button", () => {
  beforeEach(() => {
    _writeResponse = { description: "AI-generated visit description.",
                        model: "gpt-4o",
                        generated_at: "2026-02-14T10:00:00Z" };
    _writeShouldReject = null;
    vi.clearAllMocks();
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("clicking AI Write posts to the endpoint and prefills the description", async () => {
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    // Open the queue → select the row.
    await screen.findByTestId("moderation-item-chk-ai-1");
    const btn = await screen.findByTestId("checkin-ai-write-btn");
    // Baseline: in "write" mode (not undo).
    expect(btn.getAttribute("data-state")).toBe("write");

    fireEvent.click(btn);

    await waitFor(() => {
      // POST fired with the check-in id in the URL.
      const posts = api.post.mock.calls
        .filter((c) => /\/checkins\/chk-ai-1\/ai-description$/.test(c[0]));
      expect(posts.length).toBe(1);
      // Default tone forwarded as the request body per spec §1.
      expect(posts[0][1]).toEqual({ tone: "neutral_factual" });
    });

    // The description textarea now shows the AI text.
    await waitFor(() => {
      const ta = screen.getByTestId("moderation-field-description");
      expect(ta.value).toBe("AI-generated visit description.");
    });

    // Button flipped to Undo AI state.
    await waitFor(() => {
      const updated = screen.getByTestId("checkin-ai-write-btn");
      expect(updated.getAttribute("data-state")).toBe("undo");
      expect(updated.textContent).toContain("Undo AI");
    });
  });

  it("Undo AI restores the pre-AI content", async () => {
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    await screen.findByTestId("moderation-item-chk-ai-1");
    const btn = await screen.findByTestId("checkin-ai-write-btn");

    // First click — AI overwrites the field.
    fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.getByTestId("moderation-field-description").value)
        .toBe("AI-generated visit description.");
    });

    // Second click — Undo restores the pre-AI value (the hand-
    // written tech note that was on the row when we opened it).
    const undoBtn = await screen.findByTestId("checkin-ai-write-btn");
    fireEvent.click(undoBtn);

    await waitFor(() => {
      expect(screen.getByTestId("moderation-field-description").value)
        .toBe("hand-written by tech");
    });

    // Button flipped back to Write mode.
    await waitFor(() => {
      const flipped = screen.getByTestId("checkin-ai-write-btn");
      expect(flipped.getAttribute("data-state")).toBe("write");
      expect(flipped.textContent).toContain("AI Write");
    });
  });

  it("shows a rate-limit toast with correct minutes on 429", async () => {
    // Fake a rate-limit response — the api.js fetch wrapper throws
    // an Error with .status + .data.detail. Simulate that shape.
    const err = new Error("Rate limit exceeded");
    err.status = 429;
    err.data = {
      detail: {
        code: "rate_limit_exceeded",
        retry_after_seconds: 900,   // 15 minutes → toast copy check
      },
    };
    _writeShouldReject = err;

    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    await screen.findByTestId("moderation-item-chk-ai-1");
    const btn = await screen.findByTestId("checkin-ai-write-btn");
    fireEvent.click(btn);

    await waitFor(() => {
      const calls = toast.error.mock.calls.map((c) => c[0]);
      const hit = calls.find((c) =>
        /rate limit reached/i.test(c) && /15 minutes/.test(c));
      expect(hit).toBeTruthy();
    });

    // Description unchanged after the failed call.
    const ta = screen.getByTestId("moderation-field-description");
    expect(ta.value).toBe("hand-written by tech");
    // Button remains in Write mode (no successful generation).
    const stillWrite = screen.getByTestId("checkin-ai-write-btn");
    expect(stillWrite.getAttribute("data-state")).toBe("write");
  });
});
