/**
 * Feb-2026 · Rules-of-Hooks lock for ``PortalServiceReportDetail``.
 *
 * Regression test for the "Rendered fewer hooks than expected"
 * crash that fired when the portal service-report detail page
 * hit the loading (``!sr``) or error (``err``) render branches.
 *
 * Root cause: ``useTenantBrand()`` was called BELOW the
 * ``if (err) return`` and ``if (!sr) return`` gates.  React
 * runs the hooks in order and expects the exact same call
 * sequence on every render — dropping into an early return
 * skips the ``useTenantBrand`` slot, so the next render (once
 * data loads) shifts the hook slot indexes and React throws.
 *
 * Fix: hoist ``useTenantBrand()`` above every early return.
 *
 * Locks all three render branches:
 *   1. Loading ``!sr && !err`` → renders the skeleton.
 *   2. Error ``err`` → renders the error card.
 *   3. Loaded ``sr`` → renders the detail card.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, waitFor,
} from "@testing-library/react";


// ── shared mocks ─────────────────────────────────────────────
const _apiGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => _apiGet(...a),
  },
}));

const _TEST_SR = "sr-hooks-test";
vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: _TEST_SR }),
  useNavigate: () => vi.fn(),
  Link: ({ to, children, ...p }) => <a href={to} {...p}>{children}</a>,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));


import { PortalServiceReportDetail } from "@/pages/portal/PortalServiceReports";


// ── fixtures ─────────────────────────────────────────────────
function _mkSr() {
  return {
    id: _TEST_SR,
    job_id: "j-1",
    submitted_at: "2025-11-04T15:30:00Z",
    template: "pool",
    chemical_readings: [],
    chemicals_added: [],
    checklist_items: [],
    photos: [],
    job_photos: [],
    water_bodies: [{ label: "Pool", type: "pool" }],
    notes: "",
  };
}


beforeEach(() => {
  _apiGet.mockReset();
});
afterEach(() => cleanup());


describe("PortalServiceReportDetail · Rules-of-Hooks stability", () => {
  it("renders the loading skeleton without a hooks-order crash", () => {
    // Pending promise → keeps the component in the ``!sr`` branch.
    _apiGet.mockReturnValue(new Promise(() => {}));

    // Should NOT throw "Rendered fewer hooks than expected".
    expect(() => render(<PortalServiceReportDetail />)).not.toThrow();
    // Loading skeleton is on-screen (the ``!sr`` branch is exercised
    // and there's no crash overlay).
    expect(
      screen.queryByTestId("portal-service-report-error"),
    ).toBeNull();
    expect(
      screen.queryByTestId("portal-service-report-detail"),
    ).toBeNull();
  });

  it("renders the error card without a hooks-order crash", async () => {
    _apiGet.mockRejectedValueOnce(new Error("not available"));
    render(<PortalServiceReportDetail />);
    const errBox = await waitFor(
      () => screen.getByTestId("portal-service-report-error"),
      { timeout: 2000 },
    );
    expect(errBox.textContent).toContain("not available");
    // No detail card renders in the error branch.
    expect(
      screen.queryByTestId("portal-service-report-detail"),
    ).toBeNull();
  });

  it("renders the loaded detail card without a hooks-order crash", async () => {
    _apiGet.mockResolvedValueOnce(_mkSr());
    render(<PortalServiceReportDetail />);
    await waitFor(
      () => screen.getByTestId("portal-service-report-detail"),
      { timeout: 2000 },
    );
    // Error card must NOT render in the happy path.
    expect(
      screen.queryByTestId("portal-service-report-error"),
    ).toBeNull();
  });
});
