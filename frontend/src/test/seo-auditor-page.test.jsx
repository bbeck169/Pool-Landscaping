/**
 * Phase SEO-A · Feb-2026 — SEO Auditor vitest coverage.
 *
 * Verifies:
 *   1. Page renders URL input + Run scan button + list.
 *   2. Recent scans table populates from GET /seo/scans.
 *   3. Selecting a row opens the detail drawer with score gauge +
 *      section headers.
 *   4. Re-scan button fires POST /seo/scans/{id}/rerun.
 *   5. Empty-state message when no scans exist.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _scans = [
  {
    id: "scan-a",
    tenant_id: "T",
    target_url: "https://example.com/",
    status: "complete",
    requested_at: "2026-02-14T09:00:00Z",
    duration_ms: 4200,
    results: {
      score: 87,
      issue_count: { critical: 0, warning: 2, notice: 1 },
    },
  },
  {
    id: "scan-b",
    tenant_id: "T",
    target_url: "https://example.com/blog",
    status: "queued",
    requested_at: "2026-02-14T09:05:00Z",
    results: null,
  },
];

const _detail = {
  id: "scan-a",
  tenant_id: "T",
  target_url: "https://example.com/",
  status: "complete",
  requested_at: "2026-02-14T09:00:00Z",
  duration_ms: 4200,
  results: {
    score: 87,
    issue_count: { critical: 0, warning: 2, notice: 1 },
    on_page: {
      title: { present: true, length: 30, value: "Example Site" },
      meta_description: { present: true, length: 120, value: "Long enough meta description that passes the SEO length check." },
      h1: { count: 1, values: ["Welcome"] },
      h2_count: 3,
      canonical: { present: true, url: "https://example.com/" },
      og_tags: { present: true, missing: [] },
      twitter_card: { present: false },
      lang_attr: { present: true, value: "en" },
      viewport: { present: true, value: "width=device-width" },
      robots_meta: { value: null, noindex: false },
      images_total: 4,
      images_missing_alt: 1,
      broken_internal_links: [],
      html_size_kb: 12.4,
      word_count: 452,
    },
    schema_org: {
      blocks_found: 1, types: ["LocalBusiness"], valid: true, warnings: [],
    },
    performance: {
      pagespeed_mobile_score: 88, pagespeed_desktop_score: 96,
      lcp_ms: 1900, cls: 0.02,
    },
    mobile_friendly: { pass: true, issues: [], heuristic: true },
    security: {
      https: true, hsts: true, x_content_type_options: true,
      referrer_policy: true, content_security_policy: false,
    },
    robots_txt: { present: true, sitemap_ref: true, disallows_all: false },
    sitemap_xml: { present: true, url_count: 12, sample_urls: [] },
  },
};

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/seo/scans?")) {
        return { items: _scans, total: _scans.length, limit: 100, offset: 0 };
      }
      if (path.startsWith("/seo/scans/scan-a")) return _detail;
      if (path.startsWith("/seo/scans/history")) {
        return { target_url: "https://example.com/",
                 points: [{ score: 70, requested_at: "2026-02-10T09:00:00Z" },
                          { score: 87, requested_at: "2026-02-14T09:00:00Z" }] };
      }
      return {};
    }),
    post: vi.fn(async (path) => {
      if (path === "/seo/scans") {
        return { scan_id: "scan-new", status: "queued",
                 target_url: "https://foo.example/" };
      }
      if (path.endsWith("/rerun")) {
        return { scan_id: "scan-rerun", status: "queued",
                 target_url: "https://example.com/" };
      }
      return {};
    }),
    patch: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

// recharts renders SVG via ResizeObserver which JSDOM doesn't ship —
// mock a stub before the component under test is imported.
if (typeof window !== "undefined" && !window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
}

import SeoAuditorPage from "@/pages/admin/SeoAuditorPage";
import { api } from "@/api";

describe("SeoAuditorPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders URL input + Run scan button", async () => {
    render(<MemoryRouter><SeoAuditorPage /></MemoryRouter>);
    expect(await screen.findByTestId("seo-auditor-title"))
      .toBeInTheDocument();
    expect(screen.getByTestId("seo-url-input")).toBeInTheDocument();
    expect(screen.getByTestId("seo-run-scan-btn")).toBeInTheDocument();
  });

  it("recent scans table populates on load", async () => {
    render(<MemoryRouter><SeoAuditorPage /></MemoryRouter>);
    await waitFor(() => {
      expect(screen.getByTestId("seo-scan-row-scan-a")).toBeInTheDocument();
      expect(screen.getByTestId("seo-scan-row-scan-b")).toBeInTheDocument();
    });
  });

  it("selecting a row opens the detail drawer with score gauge + sections",
     async () => {
    render(<MemoryRouter><SeoAuditorPage /></MemoryRouter>);
    const row = await screen.findByTestId("seo-scan-row-scan-a");
    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.getByTestId("seo-detail-summary")).toBeInTheDocument();
      expect(screen.getByTestId("seo-score-gauge")).toBeInTheDocument();
      expect(screen.getByTestId("seo-section-on-page")).toBeInTheDocument();
      expect(screen.getByTestId("seo-section-schema")).toBeInTheDocument();
      expect(screen.getByTestId("seo-section-performance"))
        .toBeInTheDocument();
      expect(screen.getByTestId("seo-section-security")).toBeInTheDocument();
    });
    // Score text renders inside the gauge (scoped to avoid list row's 87).
    const gauge = screen.getByTestId("seo-score-gauge");
    expect(gauge.textContent).toContain("87");
  });

  it("Re-scan button fires POST /seo/scans/{id}/rerun", async () => {
    render(<MemoryRouter><SeoAuditorPage /></MemoryRouter>);
    const row = await screen.findByTestId("seo-scan-row-scan-a");
    fireEvent.click(row);
    const btn = await screen.findByTestId("seo-rerun-btn");
    fireEvent.click(btn);
    await waitFor(() => {
      const calls = api.post.mock.calls
        .filter((c) => typeof c[0] === "string" && c[0].endsWith("/rerun"));
      expect(calls.length).toBe(1);
      expect(calls[0][0]).toBe("/seo/scans/scan-a/rerun");
    });
  });

  it("shows empty state when no scans exist", async () => {
    api.get.mockImplementationOnce(async (p) => {
      if (p.startsWith("/seo/scans?")) return { items: [], total: 0 };
      return {};
    });
    render(<MemoryRouter><SeoAuditorPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("seo-list-empty")).toBeInTheDocument());
  });
});
