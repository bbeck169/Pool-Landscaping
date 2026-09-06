/**
 * Phase K35 · Feb-2026 — customer-portal login redesign coverage.
 *
 * Guarantees:
 *   1. The customer-portal login route renders the logo + card +
 *      Sign In button + water-background container.
 *   2. The water background emits both ripple layers and a
 *      caustics SVG filter — the SVG-only technique the redesign
 *      is built on.
 *   3. The layout carries the ``data-login-variant="customer"``
 *      marker so QA can pin the variant assertion.
 *   4. ``prefers-reduced-motion`` doesn't break render — the
 *      inline ``<style>`` tag already includes a
 *      ``@media (prefers-reduced-motion: reduce)`` rule that
 *      freezes both ripple animations and hides the caustics
 *      ``<animate>`` node.  This test asserts the CSS rule text
 *      is present in the DOM so a future refactor can't drop it
 *      silently.
 */
import { describe, it, expect } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render } from "@testing-library/react";
import React from "react";

import PortalWaterBackground from "../components/portal/PortalWaterBackground";


// Minimal AuthProvider stub so ``useAuth`` doesn't blow up.
vi.mock("@/auth", () => ({
  useAuth: () => ({ isAuthenticated: false, login: async () => ({}) }),
}));
vi.mock("@/theme", () => ({
  gradients: { navyToGreen: { css: "" } },
  colors: { primary: "#000", muted: "#666" },
  font: { family: "system-ui, sans-serif" },
}));
vi.mock("@/api", () => ({ api: { post: async () => ({}) } }));
vi.mock("@/utils/env", () => ({ isPreviewOrDev: () => false }));
vi.mock("@/components/auth/PreviewDemoLogins", () => ({
  PreviewDemoLogins: () => null,
}));

import Login from "../pages/Login";
import { vi } from "vitest";


function renderPortalLogin() {
  return render(
    <MemoryRouter initialEntries={["/portal/login"]}>
      <Login variant="customer" />
    </MemoryRouter>,
  );
}


describe("<PortalWaterBackground />", () => {
  it("renders both ripple layers + the caustics SVG filter", () => {
    const { getByTestId, container } = render(<PortalWaterBackground />);
    expect(getByTestId("portal-water-bg")).toBeTruthy();
    expect(getByTestId("portal-water-ripple-1")).toBeTruthy();
    expect(getByTestId("portal-water-ripple-2")).toBeTruthy();
    // Caustics filter must be defined.
    const filter = container.querySelector("filter#k35-caustics");
    expect(filter).not.toBeNull();
    // feTurbulence + feDisplacementMap present — the SVG-only
    // technique the redesign is built on.
    expect(container.querySelector("feTurbulence")).not.toBeNull();
    expect(container.querySelector("feDisplacementMap")).not.toBeNull();
  });

  it("includes a @media (prefers-reduced-motion: reduce) rule in its inline style", () => {
    const { container } = render(<PortalWaterBackground />);
    const styleText = Array.from(container.querySelectorAll("style"))
      .map((s) => s.textContent).join("");
    expect(styleText).toMatch(/prefers-reduced-motion:\s*reduce/);
    // The rule must freeze animations, not just tweak them.
    expect(styleText).toMatch(/animation:\s*none/);
  });
});


describe("Portal login layout (Login.jsx · variant=customer)", () => {
  it("renders logo, card, water background, and Sign In button", () => {
    const { getByTestId } = renderPortalLogin();
    expect(getByTestId("portal-login-page")).toBeTruthy();
    expect(getByTestId("portal-water-bg")).toBeTruthy();
    expect(getByTestId("portal-login-logo")).toBeTruthy();
    expect(getByTestId("portal-login-card")).toBeTruthy();
    expect(getByTestId("portal-login-heading").textContent)
      .toContain("Customer Portal");
    expect(getByTestId("login-email-input")).toBeTruthy();
    expect(getByTestId("login-password-input")).toBeTruthy();
    expect(getByTestId("login-submit-button").textContent)
      .toMatch(/Sign In/);
    expect(getByTestId("portal-login-back-link")).toBeTruthy();
    expect(getByTestId("login-forgot-password-link")).toBeTruthy();
  });

  it("carries a data-login-variant=customer marker on the root", () => {
    const { getByTestId } = renderPortalLogin();
    expect(getByTestId("portal-login-page")
      .getAttribute("data-login-variant"))
      .toBe("customer");
  });
});
