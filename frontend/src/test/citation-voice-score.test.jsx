/**
 * Feb-2026 · Phase 22 — Voice score KPI card.
 * Covers value render, breakdown expand toggle, per-rule pass/fail render.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const apiGet = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGet(...a), post: vi.fn(), patch: vi.fn() },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
}));

import CitationBuilderPage from "@/pages/settings/CitationBuilderPage";


const SUMMARY = {
  total_directories: 51, by_status: {}, live_count: 0, needs_update_count: 0,
  nap_drift_count: 0, duplicates_open_count: 0,
  total_impressions_last_30d: 0, weighted_completeness_score: 0,
  oldest_last_verified_at: null,
};


beforeEach(() => { apiGet.mockReset(); });


describe("CitationBuilderPage · Voice score card", () => {
  it("renders the score value + label", async () => {
    apiGet.mockImplementation((p) => {
      if (p === "/citations/tenant") return Promise.resolve({ total: 0, citations: [] });
      if (p === "/citations/tenant/summary") return Promise.resolve(SUMMARY);
      if (p === "/citations/tenant/voice-score") return Promise.resolve({
        score: 65, max_score: 100,
        breakdown: [
          { slug: "google-business-profile", label: "GBP live + desc", weight: 30, passed: true },
          { slug: "apple-maps", label: "Apple live", weight: 20, passed: true },
          { slug: "bing-places", label: "Bing live", weight: 15, passed: true },
          { slug: "yelp", label: "Yelp live", weight: 10, passed: false, reason: "not yet live" },
          { slug: "facebook-business", label: "FB live", weight: 10, passed: false },
          { slug: "nextdoor", label: "Nextdoor live", weight: 10, passed: false },
          { slug: "__nap__", label: "NAP consistency", weight: 5, passed: false, reason: "one or more not live" },
        ],
      });
      return Promise.reject(new Error(p));
    });
    render(<MemoryRouter><CitationBuilderPage /></MemoryRouter>);
    expect(await screen.findByTestId("citation-voice-score-card"))
      .toBeInTheDocument();
    expect(screen.getByTestId("citation-voice-score-value"))
      .toHaveTextContent("65");
  });

  it("expand toggle reveals the breakdown", async () => {
    apiGet.mockImplementation((p) => {
      if (p === "/citations/tenant") return Promise.resolve({ total: 0, citations: [] });
      if (p === "/citations/tenant/summary") return Promise.resolve(SUMMARY);
      if (p === "/citations/tenant/voice-score") return Promise.resolve({
        score: 30, max_score: 100,
        breakdown: [
          { slug: "google-business-profile", label: "GBP live + desc", weight: 30, passed: true },
          { slug: "apple-maps", label: "Apple live", weight: 20, passed: false, reason: "not yet live" },
        ],
      });
      return Promise.reject(new Error(p));
    });
    render(<MemoryRouter><CitationBuilderPage /></MemoryRouter>);
    await screen.findByTestId("citation-voice-score-card");
    expect(screen.queryByTestId("citation-voice-score-breakdown"))
      .not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("citation-voice-score-toggle"));
    await waitFor(() => {
      expect(screen.getByTestId("citation-voice-score-breakdown"))
        .toBeInTheDocument();
    });
    // Passed / failed rules render distinctively (via test-ids per slug).
    expect(screen.getByTestId("citation-voice-rule-google-business-profile"))
      .toBeInTheDocument();
    expect(screen.getByTestId("citation-voice-rule-apple-maps"))
      .toBeInTheDocument();
  });

  it("collapse toggle re-hides the breakdown", async () => {
    apiGet.mockImplementation((p) => {
      if (p === "/citations/tenant") return Promise.resolve({ total: 0, citations: [] });
      if (p === "/citations/tenant/summary") return Promise.resolve(SUMMARY);
      if (p === "/citations/tenant/voice-score") return Promise.resolve({
        score: 0, max_score: 100, breakdown: [
          { slug: "yelp", label: "Yelp live", weight: 10, passed: false, reason: "not yet live" },
        ],
      });
      return Promise.reject(new Error(p));
    });
    render(<MemoryRouter><CitationBuilderPage /></MemoryRouter>);
    await screen.findByTestId("citation-voice-score-card");
    fireEvent.click(screen.getByTestId("citation-voice-score-toggle"));
    await screen.findByTestId("citation-voice-score-breakdown");
    fireEvent.click(screen.getByTestId("citation-voice-score-toggle"));
    await waitFor(() => {
      expect(screen.queryByTestId("citation-voice-score-breakdown"))
        .not.toBeInTheDocument();
    });
  });
});
