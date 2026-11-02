/**
 * Nov-2026 · TD-portal-next-service-tile-title-swap — regression suite.
 *
 * Locks the sub-label swap on the "Next Pool Service" + "Next
 * Landscape Service" tiles at ``PortalHome.jsx:427-456``.
 *
 * Pre-ticket:  ``sub = service_type || ""``
 * Post-ticket: ``sub = title || service_type || ""``
 *
 * Fallback rationale: operator asked for job title in place of
 * service type, but the ``title`` field is nullable (recurring
 * jobs may never have been given one).  Falling back to
 * ``service_type`` on an empty title avoids a blank sub-label.
 * Final ``|| ""`` guards against both being null/undefined
 * (preserves the pre-ticket safe-render contract).
 *
 * BE payload is unchanged — ``_as_service`` at
 * ``backend/routers/customer_portal.py:244-255`` already returns
 * both ``service_type`` (cascaded) AND ``title`` (verbatim).  This
 * is pure FE wiring.
 *
 * Assertions:
 *   1. Pool tile renders ``title`` when it's set + non-empty.
 *   2. Landscape tile renders ``title`` when it's set + non-empty.
 *   3. Pool tile falls back to ``service_type`` when title is
 *      ``null``.
 *   4. Landscape tile falls back to ``service_type`` when title is
 *      ``""`` (empty string).
 *   5. Pool tile falls back to ``service_type`` when title is
 *      ``undefined`` (field missing entirely).
 *   6. Primary date value line is UNCHANGED — regression lock on
 *      the Pool/Landscape tile shape.
 *   7. Tile hides when both pool + landscape are null — regression
 *      lock on the shipped eligibility empty-state from Phase 3d.
 *   8. Tooltip uses the SAME resolved label as the sub-label (not
 *      service_type when title is shown).
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


beforeEach(() => { getMock.mockReset(); });
afterEach(() => cleanup());


describe("Portal next-service tile · title-with-fallback sub-label", () => {
  it("1. pool tile renders title when title is set + non-empty", async () => {
    _applySummaryMock(_mkSummary({
      pool: {
        job_id: "jp", date: "2026-11-06",
        scheduled_start: "2026-11-06T09:00:00Z",
        service_type: "Pool Cleaning",
        title: "Install Chlorinator Replacement",
      },
      landscape: null,
    }));
    _render();
    const tile = await screen.findByTestId("tile-next-service-pool");
    expect(tile.textContent).toContain("Install Chlorinator Replacement");
    expect(tile.textContent).not.toContain("Pool Cleaning");
  });

  it("2. landscape tile renders title when title is set + non-empty", async () => {
    _applySummaryMock(_mkSummary({
      pool: null,
      landscape: {
        job_id: "jl", date: "2026-11-04",
        scheduled_start: "2026-11-04T09:00:00Z",
        service_type: "Landscape Maintenance",
        title: "Install New Plants in Front Yard",
      },
    }));
    _render();
    const tile = await screen.findByTestId("tile-next-service-landscape");
    expect(tile.textContent).toContain("Install New Plants in Front Yard");
    expect(tile.textContent).not.toContain("Landscape Maintenance");
  });

  it("3. pool tile falls back to service_type when title is null", async () => {
    _applySummaryMock(_mkSummary({
      pool: {
        job_id: "jp", date: "2026-11-06",
        scheduled_start: "2026-11-06T09:00:00Z",
        service_type: "Pool Cleaning",
        title: null,
      },
      landscape: null,
    }));
    _render();
    const tile = await screen.findByTestId("tile-next-service-pool");
    expect(tile.textContent).toContain("Pool Cleaning");
  });

  it("4. landscape tile falls back to service_type when title is empty string", async () => {
    _applySummaryMock(_mkSummary({
      pool: null,
      landscape: {
        job_id: "jl", date: "2026-11-04",
        scheduled_start: "2026-11-04T09:00:00Z",
        service_type: "Landscape Maintenance",
        title: "",
      },
    }));
    _render();
    const tile = await screen.findByTestId("tile-next-service-landscape");
    expect(tile.textContent).toContain("Landscape Maintenance");
  });

  it("5. pool tile falls back to service_type when title field is missing", async () => {
    _applySummaryMock(_mkSummary({
      pool: {
        job_id: "jp", date: "2026-11-06",
        scheduled_start: "2026-11-06T09:00:00Z",
        service_type: "Pool Cleaning",
        // title: field absent entirely
      },
      landscape: null,
    }));
    _render();
    const tile = await screen.findByTestId("tile-next-service-pool");
    expect(tile.textContent).toContain("Pool Cleaning");
  });

  it("6. primary date value line is unchanged (regression lock)", async () => {
    _applySummaryMock(_mkSummary({
      pool: {
        job_id: "jp", date: "2026-11-06",
        scheduled_start: "2026-11-06T09:00:00Z",
        service_type: "Pool Cleaning",
        title: "Install Chlorinator Replacement",
      },
      landscape: {
        job_id: "jl", date: "2026-11-04",
        scheduled_start: "2026-11-04T09:00:00Z",
        service_type: "Landscape Maintenance",
        title: "Install New Plants in Front Yard",
      },
    }));
    _render();
    // ``fmtServiceDate`` renders a day-of-week + month + day format
    // (e.g. "Fri, Nov 6" / "Wed, Nov 4"); match loosely on the day
    // numeral so the regression test is resilient to the exact
    // date formatting primitive.
    const pool = await screen.findByTestId("tile-next-service-pool");
    expect(pool.textContent).toMatch(/Nov\s*6|6 Nov|11\/06|Nov\s*06/);
    const land = await screen.findByTestId("tile-next-service-landscape");
    expect(land.textContent).toMatch(/Nov\s*4|4 Nov|11\/04|Nov\s*04/);
  });

  it("7. row hides when both pool + landscape are null (empty-state)", async () => {
    _applySummaryMock(_mkSummary({ pool: null, landscape: null }));
    _render();
    await waitFor(() => {
      expect(
        screen.queryByTestId("portal-next-service-split-row"),
      ).toBeNull();
    });
    expect(screen.queryByTestId("tile-next-service-pool")).toBeNull();
    expect(screen.queryByTestId("tile-next-service-landscape")).toBeNull();
  });

  it("8. tooltip uses the same resolved label as sub-label", async () => {
    _applySummaryMock(_mkSummary({
      pool: {
        job_id: "jp", date: "2026-11-06",
        scheduled_start: "2026-11-06T09:00:00Z",
        service_type: "Pool Cleaning",
        title: "Install Chlorinator Replacement",
      },
      landscape: null,
    }));
    _render();
    const tile = await screen.findByTestId("tile-next-service-pool");
    const tooltip = tile.getAttribute("title")
      || tile.querySelector("[title]")?.getAttribute("title");
    expect(tooltip).toContain("Install Chlorinator Replacement");
    // service_type stays OUT of the tooltip when title is present —
    // guards against a mix-and-match where sub-label uses title but
    // tooltip shows service_type.
    expect(tooltip).not.toContain("Pool Cleaning");
  });
});
