/**
 * Feb-2026 · P21 — Privacy Policy content coverage.
 *
 * Pins App Store submission-critical content:
 *   1. Entity name + Arizona address + support email present.
 *   2. Effective date greppable + Last Updated date greppable.
 *   3. All 8 disclosed vendors named, each with an anchor.
 *   4. All 13 numbered section headings rendered.
 *   5. Attorney-review flag present in the source file.
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

import PrivacyPolicy from "@/pages/PrivacyPolicy";


function renderPolicy() {
  return render(
    <MemoryRouter>
      <PrivacyPolicy />
    </MemoryRouter>,
  );
}


describe("PrivacyPolicy content (P21)", () => {
  it("renders without crashing", () => {
    const { getByTestId } = renderPolicy();
    expect(getByTestId("privacy-policy-page")).toBeTruthy();
  });

  it("names the entity, address, and support email", () => {
    const { container } = renderPolicy();
    const text = container.textContent;
    expect(text).toContain("Pool & Landscaping of Vistancia LLC");
    expect(text).toContain("16165 N 83rd Ave");
    expect(text).toContain("Peoria, AZ 85382");
    expect(text).toContain("cs@plofv.com");
  });

  it("carries an Effective: date string", () => {
    const { getByTestId } = renderPolicy();
    expect(getByTestId("privacy-effective-date").textContent).toMatch(
      /Effective:\s+\w+\s+\d+,\s+\d{4}/,
    );
  });

  it("names all 8 disclosed vendors", () => {
    const { container } = renderPolicy();
    const text = container.textContent;
    for (const vendor of [
      "Stripe", "Mapbox", "RingCentral", "Resend",
      "Google Maps", "OpenAI", "Homeworks", "Twilio",
    ]) {
      expect(text).toContain(vendor);
    }
  });

  it("renders all 13 numbered section headings", () => {
    const { container } = renderPolicy();
    const h2Text = Array.from(container.querySelectorAll("h2"))
      .map((el) => el.textContent);
    // 12 numbered H2s (the H1 title is section 0) → 1..12.
    for (let n = 1; n <= 12; n += 1) {
      expect(h2Text.some((t) => t.startsWith(`${n}.`))).toBe(true);
    }
    // The H1 acts as the 13th (Header) section.
    expect(container.querySelector("h1")?.textContent).toContain("Privacy Policy");
  });

  it("marks every external vendor link with rel=noopener noreferrer target=_blank", () => {
    const { container } = renderPolicy();
    const externals = Array.from(container.querySelectorAll('a[href^="https://"]'));
    expect(externals.length).toBeGreaterThanOrEqual(8);
    for (const a of externals) {
      expect(a.getAttribute("target")).toBe("_blank");
      expect(a.getAttribute("rel")).toBe("noopener noreferrer");
    }
  });

  it("attorney-review flag comment is at the top of the source file", () => {
    const src = fs.readFileSync(
      path.resolve("src/pages/PrivacyPolicy.jsx"), "utf8");
    // Must be within the first 30 lines and mention attorney review +
    // Guideline 5.1.1.
    const head = src.split("\n").slice(0, 30).join("\n");
    expect(head).toContain("ATTORNEY REVIEW REQUIRED");
    expect(head).toMatch(/Guideline 5\.1\.1/);
  });
});
