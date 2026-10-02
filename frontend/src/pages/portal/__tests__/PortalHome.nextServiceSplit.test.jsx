/**
 * Feb-2026 · Phase 3d-portal · Next-service split UI.
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


function _mkSummary({ pool, landscape }) {
  const mirror = pool || landscape || null;
  return {
    balance_due: 0,
    past_due: 0,
    credit: 0,
    next_pool_service: pool,
    next_landscape_service: landscape,
    next_service: mirror,
    breakdown: { open_invoice_count: 0, past_due_invoice_count: 0 },
  };
}


function _applySummaryMock(summary) {
  getMock.mockImplementation((url) => {
    if (url === "/customer-portal/summary") {
      return Promise.resolve(summary);
    }
    return Promise.resolve({});
  });
}


const _render = () => render(
  <MemoryRouter initialEntries={["/portal/home"]}>
    <PortalHome />
  </MemoryRouter>,
);


const _POOL = {
  job_id: "jp",
  date: "2026-10-05",
  scheduled_start: "2026-10-05T09:00:00Z",
  service_type: "Pool cleaning",
  title: "Pool visit",
};
const _LAND = {
  job_id: "jl",
  date: "2026-10-07",
  scheduled_start: "2026-10-07T09:00:00Z",
  service_type: "Lawn trim",
  title: "Landscape visit",
};


beforeEach(() => { getMock.mockReset(); });
afterEach(() => cleanup());


describe("PortalHome · Phase 3d-portal · next-service split", () => {
  it("renders BOTH tiles when pool + landscape are both present", async () => {
    _applySummaryMock(_mkSummary({ pool: _POOL, landscape: _LAND }));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("tile-next-service-pool")).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("tile-next-service-landscape"),
    ).toBeInTheDocument();
  });

  it("renders ONLY pool tile when only pool is present", async () => {
    _applySummaryMock(_mkSummary({ pool: _POOL, landscape: null }));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("tile-next-service-pool")).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("tile-next-service-landscape"),
    ).toBeNull();
  });

  it("renders ONLY landscape tile when only landscape is present", async () => {
    _applySummaryMock(_mkSummary({ pool: null, landscape: _LAND }));
    _render();
    await waitFor(() =>
      expect(
        screen.getByTestId("tile-next-service-landscape"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("tile-next-service-pool"),
    ).toBeNull();
  });

  it("renders NEITHER tile when both are null", async () => {
    _applySummaryMock(_mkSummary({ pool: null, landscape: null }));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("portal-home")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("tile-next-service-pool")).toBeNull();
    expect(screen.queryByTestId("tile-next-service-landscape")).toBeNull();
  });
});
