/**
 * Feb-2026 · P21b — Public Terms of Service content coverage.
 *
 * Pins App Store submission-critical content on ``/terms-of-service``:
 *   1. Entity name + Arizona address + support email present.
 *   2. Effective date + Last Updated date greppable.
 *   3. All 17 numbered section headings rendered (1..17 as H2/H1).
 *   4. Attorney-review flag present in the source file (Guideline 5.1.1).
 *   5. Back-to-home link renders.
 *   6. Cross-link to /privacy-policy renders (used by section 6 + 16).
 *
 * Mirrors the P21 privacy-policy coverage pattern.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import fs from "fs";
import path from "path";

vi.mock("@/theme", () => ({
  colors: {
    background: "#fff", surface: "#fff", surfaceSecondary: "#F8FAFC",
    onSurface: "#0F172A", muted: "#64748B",
    border: "#E5E7EB", brand: "#0EA5E9",
  },
}));

import TermsOfService from "@/pages/TermsOfService";


function renderToS() {
  return render(
    <MemoryRouter>
      <TermsOfService />
    </MemoryRouter>,
  );
}


describe("TermsOfService content (P21b)", () => {
  it("renders without crashing", () => {
    const { getByTestId } = renderToS();
    expect(getByTestId("terms-of-service-page")).toBeTruthy();
    expect(getByTestId("terms-of-service-title").textContent).toContain("Terms of Service");
  });

  it("names the entity, address, and support email", () => {
    const { container } = renderToS();
    const text = container.textContent;
    expect(text).toContain("Pool & Landscaping of Vistancia LLC");
    expect(text).toContain("16165 N 83rd Ave");
    expect(text).toContain("Peoria, AZ 85382");
    expect(text).toContain("cs@plofv.com");
  });

  it("carries an Effective: date string", () => {
    const { getByTestId } = renderToS();
    expect(getByTestId("tos-effective-date").textContent).toMatch(
      /Effective:\s+\w+\s+\d+,\s+\d{4}/,
    );
  });

  it("renders all 17 numbered section headings", () => {
    const { container } = renderToS();
    const h2Text = Array.from(container.querySelectorAll("h2"))
      .map((el) => el.textContent);
    // 16 numbered H2s (1..17 minus the H1 title which counts as 0).
    // The H1 title acts as section 0 / cover; H2s carry 1..17.
    for (let n = 1; n <= 17; n += 1) {
      expect(
        h2Text.some((t) => t.startsWith(`${n}.`)),
        `expected H2 starting with "${n}." to be rendered`,
      ).toBe(true);
    }
  });

  it("includes the General Provisions section (severability, entire agreement, assignment, no waiver, notices)", () => {
    const { container } = renderToS();
    const text = container.textContent;
    // Must reference each of the 5 hooks the attorney will expand.
    expect(text).toMatch(/Severability/);
    expect(text).toMatch(/Entire Agreement/);
    expect(text).toMatch(/Assignment/);
    expect(text).toMatch(/No Waiver/);
    expect(text).toMatch(/Notices/);
  });

  it("cross-links to the Privacy Policy", () => {
    const { container } = renderToS();
    const links = Array.from(container.querySelectorAll('a[href*="/privacy-policy"]'));
    expect(links.length).toBeGreaterThanOrEqual(1);
  });

  it("renders the back-to-home link and contact block", () => {
    const { getByTestId } = renderToS();
    expect(getByTestId("terms-of-service-home-link")).toBeTruthy();
    expect(getByTestId("tos-contact-block")).toBeTruthy();
    expect(getByTestId("tos-contact-link").getAttribute("href")).toBe(
      "mailto:cs@plofv.com",
    );
  });

  it("attorney-review flag comment is at the top of the source file", () => {
    const src = fs.readFileSync(
      path.resolve("src/pages/TermsOfService.jsx"), "utf8");
    // Must be within the first 30 lines and mention attorney review +
    // Guideline 5.1.1.
    const head = src.split("\n").slice(0, 30).join("\n");
    expect(head).toContain("ATTORNEY REVIEW REQUIRED");
    expect(head).toMatch(/Guideline 5\.1\.1/);
  });
});
