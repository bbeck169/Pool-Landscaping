/**
 * AIDescriptionRewriteButton · Feb-2026 tests.
 *
 * Covers:
 *   1. Renders the sparkle icon + label.
 *   2. Disabled when draft is empty.
 *   3. Click POSTs to /checkins/rewrite-description, spinner shows.
 *   4. Success — parent callback receives the rewritten text, toast fires.
 *   5. 429 rate-limited — friendly toast, callback NOT called.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

// ── Mock the api module before importing the component. ──
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: { post: (...args) => postMock(...args) },
}));

// ── Mock sonner toast so we can assert on it. ──
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...a) => toastSuccess(...a),
    error: (...a) => toastError(...a),
  },
}));

import AIDescriptionRewriteButton from "@/components/ai/AIDescriptionRewriteButton";

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  postMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("AIDescriptionRewriteButton", () => {
  it("renders with a sparkle icon + label", () => {
    render(
      <AIDescriptionRewriteButton
        draft="hello"
        onRewritten={() => {}}
      />,
    );
    expect(screen.getByTestId("ai-rewrite-description-btn")).toBeInTheDocument();
    expect(screen.getByTestId("ai-rewrite-description-btn-icon")).toBeInTheDocument();
    expect(screen.getByText(/rewrite with ai/i)).toBeInTheDocument();
  });

  it("is disabled when draft is empty", () => {
    render(
      <AIDescriptionRewriteButton draft="   " onRewritten={() => {}} />,
    );
    const btn = screen.getByTestId("ai-rewrite-description-btn");
    expect(btn).toBeDisabled();
  });

  it("click POSTs to /checkins/rewrite-description with draft + context, shows spinner", async () => {
    let resolveFn;
    postMock.mockImplementation(
      () => new Promise((r) => { resolveFn = r; }),
    );
    const onRewritten = vi.fn();
    render(
      <AIDescriptionRewriteButton
        draft="replaced filter"
        context={{ service_category: "Pool Cleaning" }}
        onRewritten={onRewritten}
      />,
    );
    const btn = screen.getByTestId("ai-rewrite-description-btn");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(postMock).toHaveBeenCalledTimes(1);
    });
    expect(postMock).toHaveBeenCalledWith(
      "/checkins/rewrite-description",
      {
        draft_description: "replaced filter",
        context: { service_category: "Pool Cleaning" },
      },
    );
    // Spinner visible while promise is pending.
    expect(screen.getByTestId("ai-rewrite-description-btn-spinner"))
      .toBeInTheDocument();
    // Resolve the promise so cleanup happens.
    resolveFn({ rewritten: "polished text", original: "replaced filter" });
    await waitFor(() => {
      expect(onRewritten).toHaveBeenCalledWith("polished text");
    });
  });

  it("success replaces draft via callback + fires success toast", async () => {
    postMock.mockResolvedValueOnce({
      rewritten: "AI-polished description of the work",
      original: "did stuff",
    });
    const onRewritten = vi.fn();
    render(
      <AIDescriptionRewriteButton draft="did stuff" onRewritten={onRewritten} />,
    );
    fireEvent.click(screen.getByTestId("ai-rewrite-description-btn"));
    await waitFor(() => {
      expect(onRewritten).toHaveBeenCalledWith(
        "AI-polished description of the work",
      );
    });
    expect(toastSuccess).toHaveBeenCalledWith(
      expect.stringMatching(/ai rewrite applied/i),
    );
    expect(toastError).not.toHaveBeenCalled();
  });

  it("429 rate-limit shows friendly toast + does not call onRewritten", async () => {
    // Our fetch wrapper throws with a message; simulate the 429 shape.
    const err = new Error("rate_limited");
    err.status = 429;
    postMock.mockRejectedValueOnce(err);
    const onRewritten = vi.fn();
    render(
      <AIDescriptionRewriteButton draft="anything" onRewritten={onRewritten} />,
    );
    fireEvent.click(screen.getByTestId("ai-rewrite-description-btn"));
    await waitFor(() => {
      expect(toastError).toHaveBeenCalledWith(
        expect.stringMatching(/hit the rewrite limit/i),
      );
    });
    expect(onRewritten).not.toHaveBeenCalled();
  });

  it("generic error shows fallback toast", async () => {
    postMock.mockRejectedValueOnce(new Error("boom"));
    const onRewritten = vi.fn();
    render(
      <AIDescriptionRewriteButton draft="draft" onRewritten={onRewritten} />,
    );
    fireEvent.click(screen.getByTestId("ai-rewrite-description-btn"));
    await waitFor(() => {
      expect(toastError).toHaveBeenCalledWith(
        expect.stringMatching(/ai rewrite failed/i),
      );
    });
    expect(onRewritten).not.toHaveBeenCalled();
  });
});
