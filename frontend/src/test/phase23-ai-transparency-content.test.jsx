/**
 * Feb-2026 · P23 — Public AI Transparency page content coverage.
 *
 * Pins App Store submission-critical content on ``/ai-transparency``:
 *   1. Renders without crashing + effective date.
 *   2. All 5 sections (At-a-glance / Surfaces / Rights / Providers /
 *      Report a concern) present.
 *   3. Every AI surface enumerated in P22 is named in the surface
 *      table (Marina, service note rewrites, water photo, review
 *      replies, Vizzy, Dexter, churn/retention, Lana, Estimator,
 *      SEO/GBP, Admin Copilot).
 *   4. Attorney-review comment present in the top 30 lines of the
 *      source (Apple Guideline 5.1.1 reference).
 *   5. Contact email ``cs@plofv.com`` present.
 *   6. Cross-link back to ``/privacy-policy`` renders.
 *   7. Login footer includes ``AI Transparency`` link alongside the
 *      Privacy Policy and Terms of Service links.
 *   8. Privacy Policy cross-links to ``/ai-transparency`` from §4.
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
  gradients: { navyToGreen: { css: "linear-gradient(180deg, #fff, #fff)" } },
  font: { display: "sans-serif", body: "sans-serif" },
}));

// Login destructures ``login`` and ``me`` from ``useAuth()``.
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: null, me: null, login: vi.fn() }),
}));

import AiTransparency from "@/pages/AiTransparency";
import Login from "@/pages/Login";
import PrivacyPolicy from "@/pages/PrivacyPolicy";


function renderPage(el) {
  return render(<MemoryRouter>{el}</MemoryRouter>);
}


describe("AiTransparency content (P23)", () => {
  it("renders without crashing", () => {
    const { getByTestId } = renderPage(<AiTransparency />);
    expect(getByTestId("ai-transparency-page")).toBeTruthy();
    expect(getByTestId("ai-transparency-title").textContent)
      .toContain("AI Transparency");
  });

  it("carries an Effective: date string", () => {
    const { getByTestId } = renderPage(<AiTransparency />);
    expect(getByTestId("ai-transparency-effective-date").textContent)
      .toMatch(/Effective:\s+\w+\s+\d+,\s+\d{4}/);
  });

  it("renders all 5 numbered section headings", () => {
    const { container } = renderPage(<AiTransparency />);
    const h2Text = Array.from(container.querySelectorAll("h2"))
      .map((el) => el.textContent);
    for (let n = 1; n <= 5; n += 1) {
      expect(
        h2Text.some((t) => t.startsWith(`${n}.`)),
        `expected H2 starting with "${n}." to render`,
      ).toBe(true);
    }
  });

  it("At-a-glance summary box is present with the 3 headline claims", () => {
    const { getByTestId } = renderPage(<AiTransparency />);
    const box = getByTestId("ai-transparency-at-a-glance");
    const text = box.textContent || "";
    // (i) not for legally-effective decisions
    expect(text).toMatch(/not\s+make\s+legally-effective\s+decisions/i);
    // (ii) no name/phone/email/address in operational features
    expect(text).toMatch(/name/i);
    expect(text).toMatch(/phone/i);
    expect(text).toMatch(/email/i);
    // (iii) Admin Copilot carve-out
    expect(text).toMatch(/Admin Copilot/);
    expect(text).toMatch(/zero-retention/i);
  });

  it("lists every AI surface enumerated in P22", () => {
    const { getByTestId } = renderPage(<AiTransparency />);
    const table = getByTestId("ai-transparency-surface-table");
    const text = table.textContent || "";
    const surfaces = [
      "Marina",
      "Service note rewrites",
      "AI water photo",
      "Review reply drafts",
      "Vizzy",
      "Dexter",
      "Churn scoring",
      "retention campaign",
      "Lana",
      "estimator",
      "SEO",
      "GBP",
      "marketing",
      "Admin Copilot",
    ];
    for (const s of surfaces) {
      expect(text).toContain(s);
    }
  });

  it("Admin Copilot row explicitly discloses the PII exception", () => {
    const { getByTestId } = renderPage(<AiTransparency />);
    const table = getByTestId("ai-transparency-surface-table");
    const text = table.textContent || "";
    // The disclosure must be present verbatim so App Store reviewers
    // reading only this table row can find it.
    expect(text).toMatch(/name, email, phone, and service address/);
    expect(text).toMatch(/zero-retention/i);
    expect(text).toMatch(/not used for training/i);
  });

  it("Section 4 covers provider commitments (OpenAI, Anthropic, no ad networks)", () => {
    const { container } = renderPage(<AiTransparency />);
    const text = container.textContent || "";
    expect(text).toMatch(/OpenAI/);
    expect(text).toMatch(/Anthropic/);
    expect(text).toMatch(/not\s+used\s+to\s+train/i);
    expect(text).toMatch(/No\s+third-party\s+ad\s+networks/i);
    expect(text).toMatch(/No\s+automated\s+legal\s+decisions/i);
  });

  it("contact email cs@plofv.com is present and mailto-linked", () => {
    const { getByTestId } = renderPage(<AiTransparency />);
    const link = getByTestId("ai-transparency-contact-link");
    expect(link.getAttribute("href")).toMatch(/^mailto:cs@plofv\.com/);
    // Contact block is dedicated to the concern-reporting flow.
    expect(getByTestId("ai-transparency-contact-block").textContent)
      .toMatch(/AI transparency/);
  });

  it("cross-links back to the Privacy Policy", () => {
    const { container } = renderPage(<AiTransparency />);
    const links = Array.from(
      container.querySelectorAll('a[href*="/privacy-policy"]'),
    );
    expect(links.length).toBeGreaterThanOrEqual(1);
  });

  it("back-to-home link renders", () => {
    const { getByTestId } = renderPage(<AiTransparency />);
    expect(getByTestId("ai-transparency-home-link")).toBeTruthy();
  });

  it("attorney-review flag comment is at the top of the source file", () => {
    const src = fs.readFileSync(
      path.resolve("src/pages/AiTransparency.jsx"), "utf8");
    const head = src.split("\n").slice(0, 30).join("\n");
    expect(head).toContain("ATTORNEY REVIEW REQUIRED");
    expect(head).toMatch(/Guideline 5\.1\.1/);
  });
});


describe("Login footer includes AI Transparency link (P23)", () => {
  it("renders all three legal-footer links", () => {
    const { getByTestId } = renderPage(<Login />);
    expect(getByTestId("login-privacy-policy-link").getAttribute("href"))
      .toBe("/privacy-policy");
    expect(getByTestId("login-terms-of-service-link").getAttribute("href"))
      .toBe("/terms-of-service");
    expect(getByTestId("login-ai-transparency-link").getAttribute("href"))
      .toBe("/ai-transparency");
  });
});


describe("Privacy Policy cross-links to AI Transparency (P23)", () => {
  it("renders a link to /ai-transparency in the vendors section", () => {
    const { getByTestId } = renderPage(<PrivacyPolicy />);
    const link = getByTestId("privacy-policy-ai-transparency-link");
    expect(link).toBeTruthy();
    expect(link.getAttribute("href")).toBe("/ai-transparency");
  });
});
