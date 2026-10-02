/**
 * Feb-2026 · Phase 3d-portal · Outer white dashboard card.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, cleanup, waitFor,
} from "@testing-library/react";


const getMock = vi.fn();


vi.mock("@/api", () => ({
  api: {
    get:   (...a) => getMock(...a),
    post:  vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    put:   vi.fn().mockResolvedValue({}),
  },
  TOKEN_KEY: "token",
}));


vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: {
      id: "u1", name: "Pp Test", email: "pp@t.co",
      customer_id: "c1", role: "customer",
    },
    refreshMe: vi.fn().mockResolvedValue(undefined),
  }),
}));


import PortalHome from "@/pages/portal/PortalHome";


beforeEach(() => {
  getMock.mockReset();
  getMock.mockImplementation((url) => {
    if (url === "/customer-portal/summary") {
      return Promise.resolve({
        balance_due: 0, past_due: 0, credit: 0,
        next_pool_service: null,
        next_landscape_service: null,
        next_service: null,
        breakdown: { open_invoice_count: 0, past_due_invoice_count: 0 },
      });
    }
    return Promise.resolve({});
  });
});
afterEach(() => cleanup());


function _styleOf(el) {
  return (el.getAttribute("style") || "").toLowerCase();
}


describe("PortalHome · Phase 3d-portal · outer white dashboard card", () => {
  it("renders a portal-dashboard-card wrapper with white background", async () => {
    render(
      <MemoryRouter initialEntries={["/portal/home"]}>
        <PortalHome />
      </MemoryRouter>,
    );
    const card = await waitFor(() =>
      screen.getByTestId("portal-dashboard-card"),
    );
    const s = _styleOf(card);
    expect(s).toMatch(/#ffffff|rgb\(\s*255,\s*255,\s*255\s*\)/);
  });

  it("keeps inner stat tiles on dark colors.surface background", async () => {
    render(
      <MemoryRouter initialEntries={["/portal/home"]}>
        <PortalHome />
      </MemoryRouter>,
    );
    const bal = await waitFor(() => screen.getByTestId("tile-balance-due"));
    const s = _styleOf(bal);
    expect(s).toMatch(/#03002e|rgb\(\s*3,\s*0,\s*46\s*\)/);
  });
});
