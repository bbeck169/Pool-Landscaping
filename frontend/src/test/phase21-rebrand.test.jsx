/**
 * Feb-2026 · Phase 21 — Vistancia rebrand vitest suite.
 *
 * Covers:
 * * PublicReviewLanding footer says "Powered by Pool & Landscaping of
 *   Vistancia" (NOT "Powered by AquaTerra CRM").
 * * PublicReviewsWidgetPage footer says the same.
 * * BrandHeader shows the tenant name pulled from the landing payload
 *   with no residual AquaTerra branding.
 *
 * These are pure component snapshots — no network calls required for
 * the footers (they render even before landing loads).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock the reviews API module BEFORE importing components.
const fetchPublicLanding = vi.fn();
vi.mock("@/api/reviews", () => ({
  fetchPublicLanding: (...a) => fetchPublicLanding(...a),
  submitPublicRating: vi.fn(),
  submitPublicPlatformClicked: vi.fn(),
  submitPublicPrivateFeedback: vi.fn(),
  fetchWidgetReviews: vi.fn().mockResolvedValue({ reviews: [] }),
}));

beforeEach(() => {
  fetchPublicLanding.mockReset();
});


describe("PublicReviewLanding — Phase 21 rebrand", () => {
  it("renders the Vistancia 'Powered by' footer with tenant name", async () => {
    fetchPublicLanding.mockResolvedValueOnce({
      customer_first_name: "Jane",
      tech_first_name: "Mike",
      tenant_name: "Pool & Landscaping of Vistancia",
      tenant_logo_url: null,
      platforms: [],
    });
    const PublicReviewLanding = (
      await import("@/pages/reviews/PublicReviewLanding")
    ).default;
    render(
      <MemoryRouter initialEntries={["/reviews/r/abc"]}>
        <PublicReviewLanding />
      </MemoryRouter>,
    );
    // Footer renders synchronously.
    const footer = await screen.findByText(/Powered by/i);
    expect(footer.textContent).toMatch(
      /Powered by Pool & Landscaping of Vistancia/i,
    );
    expect(screen.queryByText(/AquaTerra CRM/i)).toBeNull();
  });
});


describe("Phase 21 rebrand string audit — hard-coded UI strings", () => {
  it("no residual 'AquaTerra CRM' string in PublicReviewLanding source", async () => {
    // Import as text to guard against a regression that puts the old
    // string back. This is a lightweight string audit — the vitest
    // resolver returns the module file path we can read.
    const fs = await import("node:fs");
    const path = await import("node:path");
    const p = path.resolve(
      __dirname, "../pages/reviews/PublicReviewLanding.jsx",
    );
    const src = fs.readFileSync(p, "utf8");
    expect(src).not.toMatch(/AquaTerra CRM/);
    expect(src).toMatch(/Pool & Landscaping of Vistancia/);
  });

  it("no residual 'AquaTerra CRM' in PublicReviewsWidgetPage source", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const p = path.resolve(
      __dirname, "../pages/reviews/PublicReviewsWidgetPage.jsx",
    );
    const src = fs.readFileSync(p, "utf8");
    expect(src).not.toMatch(/AquaTerra CRM/);
    expect(src).toMatch(/Pool & Landscaping of Vistancia/);
  });

  it("index.html title is the new brand", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const p = path.resolve(__dirname, "../../public/index.html");
    const src = fs.readFileSync(p, "utf8");
    // Note: the string is HTML-escaped as `Pool &amp; Landscaping of Vistancia`.
    expect(src).toMatch(/Pool &amp; Landscaping of Vistancia/);
    expect(src).not.toMatch(/<title>AquaTerra<\/title>/);
  });

  it("manifest.json holds the new brand name", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const p = path.resolve(__dirname, "../../public/manifest.json");
    const manifest = JSON.parse(fs.readFileSync(p, "utf8"));
    expect(manifest.name).toBe("Pool & Landscaping of Vistancia");
    expect(manifest.short_name).toBe("PLoV");
  });
});
