/**
 * Phase SEO-C · Feb-2026 — Keyword Ideation vitest.
 *
 * Verifies:
 *   1. Renders search bar + region/language selectors.
 *   2. Submit fires POST with correct body.
 *   3. Tabs switch and show filtered results (autocomplete → questions).
 *   4. Trends tab renders chart when data present.
 *   5. Trends tab renders warning banner when trends_summary.error set.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

let _mode = "ok"; // "ok" | "with_error"

const _makeResult = () => {
  const trends = _mode === "with_error"
    ? { error: "pytrends_timeout",
        interest_over_time: [], related_queries_top: [],
        related_queries_rising: [] }
    : { interest_over_time: [
          { date: "2025-08-01", value: 20 },
          { date: "2025-09-01", value: 35 },
          { date: "2025-10-01", value: 50 },
        ],
        related_queries_top: ["pool cleaning phoenix", "pool repair az"],
        related_queries_rising: ["saltwater pool phoenix"] };
  return {
    id: "lookup-x",
    tenant_id: "T",
    seed_keyword: "pool service phoenix",
    language: "en", region: "US",
    fetched_at: "2026-02-14T09:00:00Z",
    autocomplete_suggestions: [
      "pool service phoenix",
      "pool service phoenix az",
      "pool service phoenix cost",
    ],
    question_suggestions: [
      "how much does pool service cost",
      "why is pool service expensive",
    ],
    comparison_suggestions: ["pool service vs pool cleaning"],
    preposition_suggestions: ["pool service near me"],
    trends_summary: trends,
    cached: false,
  };
};

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/keywords/history"))
        return { items: [], total: 0 };
      return {};
    }),
    post: vi.fn(async () => _makeResult()),
    patch: vi.fn(), del: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

if (typeof window !== "undefined" && !window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
}

import KeywordIdeatorPage from "@/pages/admin/KeywordIdeatorPage";
import { api } from "@/api";

describe("KeywordIdeatorPage", () => {
  beforeEach(() => {
    _mode = "ok";
    vi.clearAllMocks();
  });

  it("renders search bar + region/language selectors", async () => {
    render(<MemoryRouter><KeywordIdeatorPage /></MemoryRouter>);
    expect(await screen.findByTestId("keyword-ideator-title"))
      .toBeInTheDocument();
    expect(screen.getByTestId("keyword-seed-input")).toBeInTheDocument();
    expect(screen.getByTestId("keyword-region-select")).toBeInTheDocument();
    expect(screen.getByTestId("keyword-language-select"))
      .toBeInTheDocument();
    expect(screen.getByTestId("keyword-force-refresh"))
      .toBeInTheDocument();
    expect(screen.getByTestId("keyword-ideate-btn")).toBeInTheDocument();
  });

  it("Ideate fires POST /keywords/ideate with the correct body", async () => {
    render(<MemoryRouter><KeywordIdeatorPage /></MemoryRouter>);
    fireEvent.change(await screen.findByTestId("keyword-seed-input"),
                       { target: { value: "pool service phoenix" } });
    fireEvent.change(screen.getByTestId("keyword-region-select"),
                       { target: { value: "GB" } });
    fireEvent.click(screen.getByTestId("keyword-ideate-btn"));
    await waitFor(() => {
      const calls = api.post.mock.calls
        .filter((c) => c[0] === "/keywords/ideate");
      expect(calls.length).toBe(1);
      expect(calls[0][1].seed_keyword).toBe("pool service phoenix");
      expect(calls[0][1].region).toBe("GB");
      expect(calls[0][1].language).toBe("en");
      expect(calls[0][1].force_refresh).toBe(false);
    });
  });

  it("Tabs switch — autocomplete → questions shows filtered list",
     async () => {
    render(<MemoryRouter><KeywordIdeatorPage /></MemoryRouter>);
    fireEvent.change(screen.getByTestId("keyword-seed-input"),
                       { target: { value: "pool service phoenix" } });
    fireEvent.click(screen.getByTestId("keyword-ideate-btn"));
    // Autocomplete tab is default.
    await waitFor(() =>
      expect(screen.getByTestId("chiplist-autocomplete"))
        .toBeInTheDocument());
    expect(screen.getByTestId("chip-autocomplete-0"))
      .toHaveTextContent("pool service phoenix");
    // Switch to Questions.
    fireEvent.click(screen.getByTestId("keyword-tab-questions"));
    await waitFor(() =>
      expect(screen.getByTestId("chiplist-questions"))
        .toBeInTheDocument());
    expect(screen.getByTestId("chip-questions-0").textContent)
      .toContain("how much does pool service cost");
  });

  it("Trends tab renders chart when data present", async () => {
    render(<MemoryRouter><KeywordIdeatorPage /></MemoryRouter>);
    fireEvent.change(screen.getByTestId("keyword-seed-input"),
                       { target: { value: "pool service phoenix" } });
    fireEvent.click(screen.getByTestId("keyword-ideate-btn"));
    await waitFor(() => screen.getByTestId("keyword-result-seed"));
    fireEvent.click(screen.getByTestId("keyword-tab-trends"));
    await waitFor(() => {
      expect(screen.getByTestId("trends-panel")).toBeInTheDocument();
      expect(screen.getByTestId("trends-chart")).toBeInTheDocument();
      expect(screen.getByTestId("trends-related-top")).toBeInTheDocument();
    });
    // Warning banner NOT rendered on happy path.
    expect(screen.queryByTestId("trends-warning-banner")).toBeNull();
  });

  it("Trends tab shows warning banner when trends_summary.error set",
     async () => {
    _mode = "with_error";
    render(<MemoryRouter><KeywordIdeatorPage /></MemoryRouter>);
    fireEvent.change(screen.getByTestId("keyword-seed-input"),
                       { target: { value: "pool service phoenix" } });
    fireEvent.click(screen.getByTestId("keyword-ideate-btn"));
    await waitFor(() => screen.getByTestId("keyword-result-seed"));
    fireEvent.click(screen.getByTestId("keyword-tab-trends"));
    await waitFor(() =>
      expect(screen.getByTestId("trends-warning-banner"))
        .toBeInTheDocument());
  });
});
