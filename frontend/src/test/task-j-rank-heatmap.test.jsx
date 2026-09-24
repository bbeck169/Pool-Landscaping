/**
 * Task J · Commit 6 · Feb-2026 — RankHeatmap frontend contract tests.
 *
 * Scope: the client-side surfaces the Task J commits introduced —
 *   • Commit 1 · empty-field / out-of-bounds validation banner
 *     (data-testid ``rank-heatmap-validation-error``).
 *   • Commit 2 · server-error banner + ``_mapHeatmapError``
 *     fallback matrix + loading-state text swap (data-testid
 *     ``rank-heatmap-error``).
 *
 * NOT covered here (deliberately):
 *   • The polling loop L31-39 — Task K's future migration surface,
 *     kept HANDS-OFF per the standing directive. Assertions below
 *     only fire on the POST error path where polling never starts,
 *     or on the pre-click state.
 *   • The result-grid renderer L170-224 — same reason.
 *   • The mocked banner (``rank-heatmap-mocked-banner``) — server-
 *     driven flag, unchanged by Task J.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── Mock the @/api boundary ────────────────────────────────────
// The list-load call fires on mount; we short-circuit it so the
// Recent section stays empty and the tests focus on the Generate
// error surface. Individual tests override api.post per-scenario.
vi.mock("@/api", () => ({
  api: {
    get:  vi.fn(),
    post: vi.fn(),
  },
}));


import { api } from "@/api";
import RankHeatmap from "@/pages/seo/RankHeatmap";


// Helper — build the mock Error thrown by the api.js request
// wrapper so ``_mapHeatmapError`` reads the same shape it will
// see at runtime.
function _apiErr({ status, detail }) {
  const err = new Error(
    typeof detail === "string" ? detail
      : (detail && detail.message) || `Request failed (${status})`,
  );
  err.status = status;
  err.data = { detail };
  return err;
}


beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  // Default list-load response — empty.
  api.get.mockImplementation(async (url) => {
    if (url === "/seo/rank-heatmaps") return [];
    // Poll endpoint stub — never used in the error-path tests, but
    // if a test accidentally starts polling we return an already-
    // done row so the polling loop terminates immediately.
    return { id: "test-id", status: "done", points: [] };
  });
});

afterEach(() => {
  vi.clearAllMocks();
});


// Utility — mount + assert the initial list-load call happened
// (it's the only api call on mount besides the polling one which
// stays dormant until ``current`` is set).
function _mount() {
  return render(
    <MemoryRouter>
      <RankHeatmap />
    </MemoryRouter>,
  );
}


// Fill the form with valid values (defaults are already valid,
// this helper only sets the keyword which is empty by default).
function _fillKeyword(value = "pool cleaning phoenix") {
  fireEvent.change(screen.getByTestId("rank-heatmap-kw"),
                      { target: { value } });
}


describe("Task J · RankHeatmap · validation + error surface", () => {

  // ══ (1) Empty-form Generate → validation banner ═════════════
  it("(1) empty-form Generate surfaces the validation banner + fires no network call", async () => {
    _mount();
    // No keyword typed → validation guard trips before api.post.
    fireEvent.click(screen.getByTestId("rank-heatmap-run"));
    await act(async () => { await Promise.resolve(); });

    const banner = screen.getByTestId("rank-heatmap-validation-error");
    expect(banner).toBeTruthy();
    expect(banner.textContent).toContain("Please fill all fields.");
    // Guard ran BEFORE the fetch — post never called.
    expect(api.post).not.toHaveBeenCalled();
    // No server-error banner either.
    expect(screen.queryByTestId("rank-heatmap-error")).toBeNull();
  });

  // ══ (2) 402 with server detail.message → surfaces server copy ═
  it("(2) mock 402 with server detail.message shows the server message verbatim", async () => {
    api.post.mockImplementationOnce(async () => {
      throw _apiErr({
        status: 402,
        detail: {
          detail: "feature_not_enabled",
          code: "feature_not_enabled",
          feature_key: "seo_heatmap",
          message:
            "The 'seo_heatmap' add-on is not enabled for this "
            + "tenant. Enable it from Organization Settings → "
            + "Feature Marketplace.",
        },
      });
    });
    _mount();
    _fillKeyword();
    fireEvent.click(screen.getByTestId("rank-heatmap-run"));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    const err = screen.getByTestId("rank-heatmap-error");
    expect(err.textContent).toContain(
      "The 'seo_heatmap' add-on is not enabled for this tenant.",
    );
    // Server copy WINS — the 402 fallback string does NOT appear.
    expect(err.textContent).not.toContain(
      "Feature not enabled — contact your admin",
    );
  });

  // ══ (3) 402 without detail.message → fallback copy ══════════
  it("(3) mock 402 without detail.message shows the 402 fallback copy", async () => {
    api.post.mockImplementationOnce(async () => {
      // Pydantic-list-shaped detail — not an object with .message.
      throw _apiErr({
        status: 402,
        detail: [{ loc: ["body"], msg: "no message field",
                    type: "value_error" }],
      });
    });
    _mount();
    _fillKeyword();
    fireEvent.click(screen.getByTestId("rank-heatmap-run"));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    const err = screen.getByTestId("rank-heatmap-error");
    expect(err.textContent).toContain(
      "Feature not enabled — contact your admin to activate "
      + "SEO Rank Heatmap.",
    );
  });

  // ══ (4) 422 → fallback copy ═════════════════════════════════
  it("(4) mock 422 (Pydantic array detail) shows the 422 fallback copy", async () => {
    api.post.mockImplementationOnce(async () => {
      throw _apiErr({
        status: 422,
        detail: [
          { loc: ["body", "grid_size"],
             msg: "Input should be less than or equal to 9",
             type: "less_than_equal" },
        ],
      });
    });
    _mount();
    _fillKeyword();
    fireEvent.click(screen.getByTestId("rank-heatmap-run"));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    const err = screen.getByTestId("rank-heatmap-error");
    expect(err.textContent).toContain(
      "Invalid map values — check your latitude, longitude, "
      + "grid size, and radius.",
    );
    // Ensure the raw Pydantic 'Input should be less than or equal
    // to 9' NEVER leaks through — that's the exact noise the
    // fallback exists to hide.
    expect(err.textContent).not.toContain("Input should be less than");
  });

  // ══ (5) 429 → fallback copy ═════════════════════════════════
  it("(5) mock 429 shows the 429 fallback copy", async () => {
    api.post.mockImplementationOnce(async () => {
      throw _apiErr({
        status: 429,
        detail: { code: "rate_limited" },  // no .message
      });
    });
    _mount();
    _fillKeyword();
    fireEvent.click(screen.getByTestId("rank-heatmap-run"));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    const err = screen.getByTestId("rank-heatmap-error");
    expect(err.textContent).toContain(
      "Rate limit hit — try again in a moment.",
    );
  });

  // ══ (6) Network error (no status) → generic fallback ════════
  it("(6) network error (no status) shows the generic fallback", async () => {
    api.post.mockImplementationOnce(async () => {
      // No .status set — mimics api.js's network-error throw
      // (transport error, timeout, etc.).
      throw new Error("Network error — connection refused");
    });
    _mount();
    _fillKeyword();
    fireEvent.click(screen.getByTestId("rank-heatmap-run"));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    const err = screen.getByTestId("rank-heatmap-error");
    expect(err.textContent).toContain(
      "Something went wrong. Please try again.",
    );
  });

  // ══ (7) Loading state — text swap during in-flight fetch ════
  it("(7) button text swaps to 'Running…' during in-flight fetch, restores after", async () => {
    let resolveFetch;
    api.post.mockImplementationOnce(() =>
      new Promise((_, reject) => {
        resolveFetch = () =>
          reject(_apiErr({ status: 500, detail: null }));
      }),
    );
    _mount();
    _fillKeyword();
    // Sanity — initial text.
    const btn = screen.getByTestId("rank-heatmap-run");
    expect(btn.textContent).toContain("Generate heatmap");
    expect(btn.disabled).toBe(false);

    fireEvent.click(btn);
    // Give React a tick to flush ``setStarting(true)``.
    await act(async () => { await Promise.resolve(); });

    // Mid-flight — 'Running…' + disabled.
    expect(btn.textContent).toContain("Running…");
    expect(btn.disabled).toBe(true);

    // Resolve (as rejection) → finally runs setStarting(false).
    await act(async () => {
      resolveFetch();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(btn.textContent).toContain("Generate heatmap");
    expect(btn.disabled).toBe(false);
  });

  // ══ (8) Error banner clears on next Generate click ══════════
  it("(8) error banner clears at the top of the next Generate click", async () => {
    // First click — throws.
    api.post.mockImplementationOnce(async () => {
      throw _apiErr({
        status: 500, detail: null,
      });
    });
    // Second click — resolves.
    api.post.mockImplementationOnce(async () => ({
      heatmap_id: "next-hid", status: "queued",
      mocked: false, reason: null,
    }));
    _mount();
    _fillKeyword();
    fireEvent.click(screen.getByTestId("rank-heatmap-run"));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    // First error banner surfaces.
    expect(screen.getByTestId("rank-heatmap-error")).toBeTruthy();

    // Second click — banner cleared at top of start() → gone.
    fireEvent.click(screen.getByTestId("rank-heatmap-run"));
    await act(async () => { await Promise.resolve(); });
    expect(screen.queryByTestId("rank-heatmap-error")).toBeNull();
  });

  // ══ (Bonus) 400 with plain-string detail → server copy ══════
  it("(bonus) 400 with plain-string detail surfaces the server string", async () => {
    api.post.mockImplementationOnce(async () => {
      // Legacy shape — raise HTTPException(400, "keyword required")
      throw _apiErr({
        status: 400,
        detail: "keyword required for the SERP search",
      });
    });
    _mount();
    _fillKeyword();
    fireEvent.click(screen.getByTestId("rank-heatmap-run"));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    const err = screen.getByTestId("rank-heatmap-error");
    expect(err.textContent).toContain(
      "keyword required for the SERP search",
    );
    // Fallback string does NOT appear when server sent a plain
    // string detail.
    expect(err.textContent).not.toContain("Invalid request.");
  });
});
