/**
 * Feb-2026 · Phase 22 — Citation Builder base page render + filters.
 *
 * Covers page load, KPI strip, category chip filter, status filter,
 * NAP-drift-only filter, extended filter chips (problems + high-weight
 * not started), sort dropdown, and bulk verify wiring.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPatch = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: (...a) => apiPost(...a),
    patch: (...a) => apiPatch(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(), error: vi.fn(), message: vi.fn(),
  },
}));

import CitationBuilderPage from "@/pages/settings/CitationBuilderPage";


const DEFAULT_SUMMARY = {
  total_directories: 51,
  by_status: { live: 2, not_started: 49 },
  live_count: 2,
  needs_update_count: 0,
  nap_drift_count: 1,
  duplicates_open_count: 1,
  total_impressions_last_30d: 3400,
  weighted_completeness_score: 12.5,
  oldest_last_verified_at: "2026-01-15T10:00:00Z",
};

const DEFAULT_VOICE = {
  score: 30, max_score: 100,
  breakdown: [
    { slug: "google-business-profile", label: "Google Business Profile live + description ≥ 200 chars", weight: 30, passed: true },
    { slug: "apple-maps", label: "Apple Business Connect live", weight: 20, passed: false, reason: "not yet live" },
    { slug: "bing-places", label: "Bing Places live", weight: 15, passed: false },
    { slug: "yelp", label: "Yelp live", weight: 10, passed: false },
    { slug: "facebook-business", label: "Facebook Business live", weight: 10, passed: false },
    { slug: "nextdoor", label: "Nextdoor live", weight: 10, passed: false },
    { slug: "__nap__", label: "NAP consistency (no drift on the above)", weight: 5, passed: false },
  ],
};

function mkRow(slug, overrides = {}) {
  return {
    directory_id: `dir-${slug}`,
    id: `row-${slug}`,
    directory: {
      id: `dir-${slug}`, slug, name: slug, category: "search",
      weight: 8, url: `https://${slug}.example.com`,
    },
    status: "not_started",
    listing_url: null, notes: null,
    last_verified_at: null,
    nap_drift_detected: false,
    duplicate_urls: [],
    impressions_last_30d: null,
    ...overrides,
  };
}


function mkList() {
  return {
    total: 3,
    citations: [
      mkRow("google-business-profile", {
        directory: { id: "dir-google-business-profile", slug: "google-business-profile",
          name: "Google Business Profile", category: "search", weight: 10,
          url: "https://business.google.com" },
        status: "live", impressions_last_30d: 2400,
      }),
      mkRow("apple-maps", {
        directory: { id: "dir-apple-maps", slug: "apple-maps",
          name: "Apple Business Connect", category: "search", weight: 9,
          url: "https://businessconnect.apple.com" },
        status: "needs_update", nap_drift_detected: true,
      }),
      mkRow("yelp", {
        directory: { id: "dir-yelp", slug: "yelp",
          name: "Yelp for Business", category: "local", weight: 9,
          url: "https://biz.yelp.com" },
        status: "not_started",
        duplicate_urls: [{ url: "https://dup1", status: "reported" }],
      }),
    ],
  };
}


function mockDefault() {
  apiGet.mockImplementation((path) => {
    if (path === "/citations/tenant") return Promise.resolve(mkList());
    if (path === "/citations/tenant/summary") return Promise.resolve(DEFAULT_SUMMARY);
    if (path === "/citations/tenant/voice-score") return Promise.resolve(DEFAULT_VOICE);
    return Promise.reject(new Error(`unmocked ${path}`));
  });
}


function renderPage() {
  return render(<MemoryRouter><CitationBuilderPage /></MemoryRouter>);
}


beforeEach(() => {
  apiGet.mockReset(); apiPost.mockReset(); apiPatch.mockReset();
});


describe("CitationBuilderPage — base render + filters", () => {
  it("renders title + KPI strip with all 5 tiles", async () => {
    mockDefault();
    renderPage();
    expect(await screen.findByTestId("citation-builder-title"))
      .toBeInTheDocument();
    expect(await screen.findByTestId("citation-kpi-score-value"))
      .toHaveTextContent("13"); // 12.5 rounds to display 13
    expect(screen.getByTestId("citation-kpi-live")).toHaveTextContent("2");
    expect(screen.getByTestId("citation-kpi-drift")).toHaveTextContent("1");
    expect(screen.getByTestId("citation-kpi-duplicates")).toHaveTextContent("1");
    expect(screen.getByTestId("citation-kpi-impressions"))
      .toHaveTextContent("3.4k");
  });

  it("renders row list with correct testids", async () => {
    mockDefault();
    renderPage();
    expect(await screen.findByTestId("citation-row-google-business-profile"))
      .toBeInTheDocument();
    expect(screen.getByTestId("citation-row-apple-maps")).toBeInTheDocument();
    // Drift badge only on apple-maps.
    expect(screen.getByTestId("citation-row-drift-apple-maps")).toBeInTheDocument();
    expect(screen.queryByTestId("citation-row-drift-google-business-profile"))
      .not.toBeInTheDocument();
    // Duplicate badge only on yelp.
    expect(screen.getByTestId("citation-row-dupes-yelp")).toBeInTheDocument();
  });

  it("category chip filters narrow the row list", async () => {
    mockDefault();
    renderPage();
    await screen.findByTestId("citation-row-google-business-profile");
    fireEvent.click(screen.getByTestId("citation-filter-cat-local"));
    await waitFor(() => {
      // yelp is local, others are search.
      expect(screen.getByTestId("citation-row-yelp")).toBeInTheDocument();
      expect(screen.queryByTestId("citation-row-google-business-profile"))
        .not.toBeInTheDocument();
    });
  });

  it("status filter narrows rows", async () => {
    mockDefault();
    renderPage();
    await screen.findByTestId("citation-row-google-business-profile");
    fireEvent.change(screen.getByTestId("citation-filter-status"),
                      { target: { value: "live" } });
    await waitFor(() => {
      expect(screen.getByTestId("citation-row-google-business-profile"))
        .toBeInTheDocument();
      expect(screen.queryByTestId("citation-row-yelp")).not.toBeInTheDocument();
    });
  });

  it("NAP drift only checkbox filters to drift rows", async () => {
    mockDefault();
    renderPage();
    await screen.findByTestId("citation-row-google-business-profile");
    fireEvent.click(screen.getByTestId("citation-filter-drift-only"));
    await waitFor(() => {
      expect(screen.getByTestId("citation-row-apple-maps")).toBeInTheDocument();
      expect(screen.queryByTestId("citation-row-google-business-profile"))
        .not.toBeInTheDocument();
    });
  });

  it("problems-only chip narrows to drift + duplicates rows", async () => {
    mockDefault();
    renderPage();
    await screen.findByTestId("citation-row-google-business-profile");
    fireEvent.click(screen.getByTestId("citation-filter-problems-only"));
    await waitFor(() => {
      expect(screen.getByTestId("citation-row-apple-maps")).toBeInTheDocument();
      expect(screen.getByTestId("citation-row-yelp")).toBeInTheDocument();
      expect(screen.queryByTestId("citation-row-google-business-profile"))
        .not.toBeInTheDocument();
    });
  });

  it("high-weight-not-started chip narrows to weight≥8 AND not_started", async () => {
    mockDefault();
    renderPage();
    await screen.findByTestId("citation-row-google-business-profile");
    fireEvent.click(screen.getByTestId("citation-filter-hw-notstarted"));
    await waitFor(() => {
      // yelp (weight 9, not_started) is the only match.
      expect(screen.getByTestId("citation-row-yelp")).toBeInTheDocument();
      expect(screen.queryByTestId("citation-row-google-business-profile"))
        .not.toBeInTheDocument();
      expect(screen.queryByTestId("citation-row-apple-maps"))
        .not.toBeInTheDocument();
    });
  });

  it("sort dropdown re-orders rows by impressions", async () => {
    mockDefault();
    renderPage();
    await screen.findByTestId("citation-row-google-business-profile");
    fireEvent.change(screen.getByTestId("citation-filter-sort"),
                      { target: { value: "impressions" } });
    // Google (2400) should be first.
    await waitFor(() => {
      const list = screen.getByTestId("citation-builder-list");
      const rowIds = Array.from(list.querySelectorAll('[data-testid^="citation-row-"]'))
        .map((n) => n.getAttribute("data-testid"))
        .filter((id) => /^citation-row-(google|apple|yelp)/.test(id));
      expect(rowIds[0]).toBe("citation-row-google-business-profile");
    });
  });

  it("bulk verify calls POST with selected ids", async () => {
    mockDefault();
    apiPost.mockResolvedValueOnce({ verified: 2 });
    renderPage();
    await screen.findByTestId("citation-row-google-business-profile");
    fireEvent.click(screen.getByTestId("citation-row-select-google-business-profile"));
    fireEvent.click(screen.getByTestId("citation-row-select-yelp"));
    fireEvent.click(screen.getByTestId("citation-bulk-verify"));
    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        "/citations/tenant/bulk-mark-verified",
        { directory_ids: ["dir-google-business-profile", "dir-yelp"] }
      );
    });
  });

  it("search input filters by directory name", async () => {
    mockDefault();
    renderPage();
    await screen.findByTestId("citation-row-google-business-profile");
    fireEvent.change(screen.getByTestId("citation-filter-search"),
                      { target: { value: "apple" } });
    await waitFor(() => {
      expect(screen.getByTestId("citation-row-apple-maps")).toBeInTheDocument();
      expect(screen.queryByTestId("citation-row-google-business-profile"))
        .not.toBeInTheDocument();
    });
  });
});
