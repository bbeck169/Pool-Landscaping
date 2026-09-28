/**
 * SO-A · Feb-2026 — MarcoSuggestionsPanel tests.
 *
 * Locks:
 *   1. On mount → POSTs /schedule/ai-recommendation.
 *   2. Loading skeleton renders while pending.
 *   3. On success → renders one card per suggestion with rank
 *      medals 🥇 🥈 🥉.
 *   4. apply_mode="one_click" → button reads "Apply Optimization".
 *   5. apply_mode="queued_for_approval" → button reads
 *      "Suggest Reassignment".
 *   6. 429 rate-limit response triggers a toast error and shows
 *      inline error state with a Retry button.
 *   7. Empty suggestions[] → empty state banner.
 *   8. Provider chip renders Google / OSRM / Crow-flies badge.
 */
import React from "react";
import {
  render, screen, fireEvent, waitFor, act,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(), success: vi.fn(),
    info: vi.fn(), warning: vi.fn(),
  },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: { post: vi.fn(), put: vi.fn(), get: vi.fn() },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import { MarcoSuggestionsPanel } from
  "@/components/schedule/MarcoSuggestionsPanel";

const SAMPLE_RESULT = {
  job_id: "job-x", target_date: "2026-02-16",
  apply_mode: "one_click",
  plain_english_source: "llm",
  provider_used: "google",
  compute_ms: 214,
  rate_limit: { limit: 10, window_seconds: 60, remaining: 9 },
  suggestions: [
    {
      technician_id: "t1", technician_name: "David",
      insertion_index: 1, detour_minutes: 2.3, detour_miles: 0.8,
      baseline_route_minutes: 40, with_insertion_route_minutes: 42.3,
      score: 92.3, rank: 1, provider_used: "google",
      route_len: 3,
      plain_english: "David is the best fit — this stop adds only 2 min.",
    },
    {
      technician_id: "t2", technician_name: "Sara",
      insertion_index: 0, detour_minutes: 5.6, detour_miles: 2.1,
      baseline_route_minutes: 55, with_insertion_route_minutes: 60.6,
      score: 81.3, rank: 2, provider_used: "osrm",
      route_len: 4,
      plain_english: "Sara can start with this stop.",
    },
    {
      technician_id: "t3", technician_name: "Mike",
      insertion_index: 3, detour_minutes: 12.4, detour_miles: 5.9,
      baseline_route_minutes: 62, with_insertion_route_minutes: 74.4,
      score: 58.7, rank: 3, provider_used: "google",
      route_len: 5,
      plain_english: "Mike is the last-choice fit — 12 min detour.",
    },
  ],
  unavailable_technicians: [],
  origin_source_map: {},
  generated_at: "2026-02-16T14:00:00+00:00",
};

describe("SO-A · MarcoSuggestionsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.post.mockResolvedValue(SAMPLE_RESULT);
  });

  it("mounts and POSTs to /schedule/ai-recommendation", async () => {
    render(
      <MarcoSuggestionsPanel
        jobId="job-x" targetDate="2026-02-16"
      />,
    );
    await waitFor(() => {
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/schedule/ai-recommendation",
        expect.objectContaining({
          job_id: "job-x", target_date: "2026-02-16",
          max_suggestions: 3,
        }),
      );
    });
  });

  it("renders the loading skeleton before the first response", async () => {
    let resolveNow;
    _apiMock.post.mockImplementationOnce(
      () => new Promise((res) => { resolveNow = res; }),
    );
    render(
      <MarcoSuggestionsPanel
        jobId="job-x" targetDate="2026-02-16"
      />,
    );
    expect(
      screen.getByTestId("marco-suggestions-loading"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("marco-suggestions-skeleton-1"),
    ).toBeInTheDocument();
    await act(async () => { resolveNow(SAMPLE_RESULT); });
    await waitFor(() =>
      expect(
        screen.queryByTestId("marco-suggestions-loading"),
      ).not.toBeInTheDocument(),
    );
  });

  it("renders one card per suggestion with rank medals", async () => {
    render(
      <MarcoSuggestionsPanel
        jobId="job-x" targetDate="2026-02-16"
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("marco-suggestion-card-1"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId("marco-suggestion-card-2")).toBeInTheDocument();
    expect(screen.getByTestId("marco-suggestion-card-3")).toBeInTheDocument();
    expect(
      screen.getByTestId("marco-suggestion-medal-1").textContent,
    ).toBe("🥇");
    expect(
      screen.getByTestId("marco-suggestion-medal-2").textContent,
    ).toBe("🥈");
    expect(
      screen.getByTestId("marco-suggestion-medal-3").textContent,
    ).toBe("🥉");
  });

  it("renders detour chips", async () => {
    render(
      <MarcoSuggestionsPanel jobId="job-x" targetDate="2026-02-16" />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("marco-suggestion-detour-1"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("marco-suggestion-detour-1").textContent,
    ).toMatch(/\+2\.3 min/);
  });

  it('apply_mode="one_click" → button reads "Apply Optimization"', async () => {
    render(
      <MarcoSuggestionsPanel jobId="job-x" targetDate="2026-02-16" />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("marco-suggestion-apply-1"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("marco-suggestion-apply-1").textContent,
    ).toMatch(/Apply Optimization/i);
  });

  it('apply_mode="queued_for_approval" → button reads "Suggest Reassignment"', async () => {
    _apiMock.post.mockResolvedValueOnce({
      ...SAMPLE_RESULT, apply_mode: "queued_for_approval",
    });
    render(
      <MarcoSuggestionsPanel jobId="job-x" targetDate="2026-02-16" />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("marco-suggestion-apply-1"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("marco-suggestion-apply-1").textContent,
    ).toMatch(/Suggest Reassignment/i);
  });

  it("429 rate-limit response → toast error + inline retry", async () => {
    _apiMock.post.mockRejectedValueOnce({
      status: 429,
      data: {
        detail: {
          error_code: "schedule_ai_rate_limit_exceeded",
          message: "over the limit",
          retry_after_seconds: 42,
        },
      },
    });
    render(
      <MarcoSuggestionsPanel jobId="job-x" targetDate="2026-02-16" />,
    );
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringMatching(/budget exceeded.*42s/i),
      ),
    );
    expect(
      screen.getByTestId("marco-suggestions-error"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("marco-suggestions-retry"),
    ).toBeInTheDocument();
  });

  it("empty suggestions[] → empty banner", async () => {
    _apiMock.post.mockResolvedValueOnce({
      ...SAMPLE_RESULT, suggestions: [],
    });
    render(
      <MarcoSuggestionsPanel jobId="job-x" targetDate="2026-02-16" />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("marco-suggestions-empty"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("marco-suggestions-empty").textContent,
    ).toMatch(/No optimizations found/i);
  });

  it("provider chip renders Google / OSRM / Crow-flies", async () => {
    _apiMock.post.mockResolvedValueOnce({
      ...SAMPLE_RESULT,
      suggestions: [
        { ...SAMPLE_RESULT.suggestions[0], provider_used: "osrm" },
        { ...SAMPLE_RESULT.suggestions[1], provider_used: "crowflies" },
        { ...SAMPLE_RESULT.suggestions[2], provider_used: "google" },
      ],
    });
    render(
      <MarcoSuggestionsPanel jobId="job-x" targetDate="2026-02-16" />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("marco-suggestion-provider-1"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("marco-suggestion-provider-1").textContent,
    ).toMatch(/OSRM/);
    expect(
      screen.getByTestId("marco-suggestion-provider-2").textContent,
    ).toMatch(/Crow-flies/);
    expect(
      screen.getByTestId("marco-suggestion-provider-3").textContent,
    ).toMatch(/Google/);
  });

  it("template fallback source notice renders when not LLM", async () => {
    _apiMock.post.mockResolvedValueOnce({
      ...SAMPLE_RESULT,
      plain_english_source: "template_fallback_master_off",
    });
    render(
      <MarcoSuggestionsPanel jobId="job-x" targetDate="2026-02-16" />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("marco-suggestions-fallback-notice"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("marco-suggestions-fallback-notice").textContent,
    ).toMatch(/master_off/);
  });
});
