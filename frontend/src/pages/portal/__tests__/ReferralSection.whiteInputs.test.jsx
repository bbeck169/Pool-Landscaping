/**
 * Feb-2026 · Phase 3d-portal · Refer-a-Friend inputs whitened.
 */
import React from "react";
import {
  describe, it, expect, vi, afterEach,
} from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, cleanup,
} from "@testing-library/react";


vi.mock("@/api", () => ({
  api: {
    get:   vi.fn().mockResolvedValue({}),
    post:  vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    put:   vi.fn().mockResolvedValue({}),
  },
  TOKEN_KEY: "token",
}));


vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: {
      id: "u1", email: "pp@t.co", name: "Pp Test",
      customer_id: "c1", role: "customer",
    },
    refreshMe: vi.fn().mockResolvedValue(undefined),
  }),
}));


import ReferralSection from "@/pages/portal/ReferralSection";


afterEach(() => cleanup());


const _TARGET_TESTIDS = [
  "portal-referral-friend-name",
  "portal-referral-friend-phone",
  "portal-referral-friend-email",
  "portal-referral-friend-address",
  "portal-referral-service-select",
  "portal-referral-notes",
];


function _styleOf(el) {
  return (el.getAttribute("style") || "").toLowerCase();
}


describe("ReferralSection · Phase 3d-portal · whitened inputs", () => {
  it("every input/select/textarea has white background + dark slate text", () => {
    render(<MemoryRouter><ReferralSection /></MemoryRouter>);
    for (const tid of _TARGET_TESTIDS) {
      const el = screen.getByTestId(tid);
      const s = _styleOf(el);
      expect(
        s, `${tid} background should be white`,
      ).toMatch(/#ffffff|rgb\(\s*255,\s*255,\s*255\s*\)/);
      expect(
        s, `${tid} color should be slate-900`,
      ).toMatch(/#0f172a|rgb\(\s*15,\s*23,\s*42\s*\)/);
    }
  });

  it("preserves every original testid on the six form controls", () => {
    render(<MemoryRouter><ReferralSection /></MemoryRouter>);
    for (const tid of _TARGET_TESTIDS) {
      expect(screen.getByTestId(tid)).toBeInTheDocument();
    }
  });
});
