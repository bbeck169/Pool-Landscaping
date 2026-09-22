/**
 * Phase P34 · Feb-2026 — Launch Hardening Punchlist frontend tests.
 *
 * Locks the P34 gaps we closed on the frontend:
 *
 *   Item 1 — Portal layout renders with ``pt-16`` top-padding when
 *            the current path starts with ``/portal``. Source-lint
 *            asserts the AppLayout wrapper's conditional class.
 *   Item 8 — ``AddCardPage.jsx`` renders a branded ``BrandLogo``
 *            header above the card. Verified via testId + logo alt
 *            attribute.
 *
 * Items 2-5, 7, 9, 10 are backend-locked in
 * ``backend/tests/test_p34_launch_hardening.py``. Item 6 is
 * documented as deferred in ``/app/memory/PRD.md`` (see the
 * "P34 Deferred" section).
 */
import fs from "fs";
import path from "path";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";


// ─────────────────────────────────────────────────────────────
// Item 1 — Portal layout ``pt-16`` source-lint
// ─────────────────────────────────────────────────────────────
describe("P34 · Item 1 · Portal layout pt-16", () => {
  it("AppLayout applies ``pt-16`` when on a /portal path", () => {
    const p = path.resolve(__dirname, "../layouts/AppLayout.jsx");
    const src = fs.readFileSync(p, "utf-8");
    // Look for the conditional wrapper class. We accept either
    // single-line or ternary formatting.
    expect(src).toMatch(/pathname\.startsWith\(["']\/portal["']\)\s*\?\s*["']pt-16["']/);
  });
});


// ─────────────────────────────────────────────────────────────
// Item 8 — AddCardPage branded BrandLogo header
// ─────────────────────────────────────────────────────────────
// Mock @stripe/stripe-js + @stripe/react-stripe-js so we don't
// require a real publishable key to mount the page in JSDOM.
vi.mock("@stripe/stripe-js", () => ({
  loadStripe: vi.fn(() => Promise.resolve({})),
}));
vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }) => <>{children}</>,
  useStripe: () => null,
  useElements: () => null,
  PaymentElement: () => <div data-testid="mock-payment-element" />,
}));

// Mock the tenant-brand hook so ``BrandLogo`` renders without needing
// the actual tenant fetch to resolve.
vi.mock("@/hooks/useTenantBrand", () => ({
  default: () => ({ logo_url: null, name: "P34 Test Tenant" }),
}));

// Fetch mock — the AddCardPage bootstraps by hitting the context +
// setup-intent endpoints. We simulate a "bad token" response so the
// card body renders the bootError branch (fast, deterministic) while
// the header stays visible regardless.
beforeEach(() => {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/setup-intent")) {
      return Promise.resolve({
        ok: false,
        json: () => Promise.resolve({ detail: "setup-intent not needed" }),
      });
    }
    return Promise.resolve({
      ok: false,
      json: () => Promise.resolve({ detail: "This link is no longer valid." }),
    });
  });
});

describe("P34 · Item 8 · AddCardPage branded header", () => {
  it("renders the BrandLogo header above the card", async () => {
    // Lazy import inside the test so the vi.mock() blocks above are
    // in effect before the module (which imports BrandLogo →
    // useTenantBrand) is evaluated.
    const AddCardPageModule = await import("@/pages/public/AddCardPage");
    const AddCardPage = AddCardPageModule.default;
    const { container } = render(
      <MemoryRouter initialEntries={["/portal/add-card?token=P34"]}>
        <AddCardPage />
      </MemoryRouter>,
    );
    // Header wrapper is present (synchronous — it renders on the
    // initial paint, before the fetch bootstrap resolves).
    const header = container.querySelector(
      "[data-testid='add-card-page-brand-header']",
    );
    expect(header).toBeTruthy();
    // BrandLogo link is present + points to /portal/login (public,
    // no-auth surface) instead of the role-gated "/". Note:
    // BrandLogo emits ``data-testid={testId}`` (no ``-link`` suffix)
    // on the wrapper Link when a testId is passed.
    const link = container.querySelector(
      "[data-testid='add-card-page-brand-logo']",
    );
    expect(link).toBeTruthy();
    expect(link.getAttribute("href")).toBe("/portal/login");
    // Header sits ABOVE the card body in DOM order.
    const page = container.querySelector(
      "[data-testid='phase47c-add-card-page']",
    );
    expect(page.firstElementChild).toBe(header);
  });
});
