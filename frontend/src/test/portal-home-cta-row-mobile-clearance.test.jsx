/**
 * Feb-2026 · Portal home CTA-row overlap fix.
 *
 * User reported the "Call Now" + "Request Service" pills
 * overlapping the top-header row (Sign out + bell + hamburger).
 * Fix: added `mt-12 sm:mt-0` on the CTA row wrapper so mobile
 * viewports get ~48px of clearance below the header.
 *
 * This suite locks the class list in place so a future refactor
 * that drops the mobile margin regression is caught immediately.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Minimum viable mocks so PortalHome mounts.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn().mockImplementation((path) => {
      if (String(path).includes("/portal/home")) {
        return Promise.resolve({ counts: {} });
      }
      if (String(path).includes("/customer-portal/summary")) {
        return Promise.resolve({
          balance_due: 0, past_due: 0, credit: 0,
          breakdown: {}, next_service: null,
        });
      }
      if (String(path).includes("/credits/balance")) {
        return Promise.resolve({ balance_dollars: 0 });
      }
      if (String(path).includes("/messages/unread-count")) {
        return Promise.resolve({ unread: 0 });
      }
      if (String(path).includes("/ai-employees")) {
        return Promise.resolve([]);
      }
      return Promise.resolve([]);
    }),
    post: vi.fn(), patch: vi.fn(),
  },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", name: "Test", role: "customer",
                              customer_id: "c1", email: "t@x" } }),
}));
vi.mock("@/pages/portal/CallNowButton", () => ({
  default: () => <button data-testid="portal-call-now-btn">Call Now</button>,
}));
vi.mock("@/pages/portal/PortalWalkthrough", () => ({
  default: () => null,
  usePortalWalkthrough: () => ({ isActive: false, start: () => {} }),
}));

afterEach(() => cleanup());


describe("PortalHome · CTA-row mobile top-margin fix", () => {
  it("portal-cta-row no longer requires mt-12 (P43 sticky-header retirement)",
    async () => {
      // Phase P43 · Feb-2026 — the legacy ``mt-12 sm:mt-0`` top-offset
      // hack that pushed the CTA row below the floating UniversalMenu
      // was REMOVED after the portal shell gained a proper 56px
      // sticky header (``portal-sticky-header``) inside AppLayout.
      // Retained as sunset-marker so a future accidental re-addition
      // fails CI.
      const PortalHome = (await import("@/pages/portal/PortalHome")).default;
      render(
        <MemoryRouter>
          <PortalHome />
        </MemoryRouter>,
      );
      const row = await screen.findByTestId("portal-cta-row");
      const cls = row.getAttribute("class") || "";
      expect(cls).not.toMatch(/\bmt-12\b/);
      expect(cls).toMatch(/\bmb-4\b/);
    });

  it("both CTA pills carry the required test-ids", async () => {
    const PortalHome = (await import("@/pages/portal/PortalHome")).default;
    render(
      <MemoryRouter>
        <PortalHome />
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("portal-call-now-btn")).toBeTruthy();
    expect(await screen.findByTestId("portal-request-service-btn"))
      .toBeTruthy();
  });
});
