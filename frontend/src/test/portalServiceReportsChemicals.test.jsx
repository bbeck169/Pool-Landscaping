/**
 * Feb-2026 · Pool Service PS-B — portal chemicals display fallback.
 *
 * Pins the four fallback fixtures from the PS-B brief:
 *   (a) top-level populated → renders top-level, ignores
 *       ``water_bodies[0]``.
 *   (b) top-level empty + ``water_bodies[0]`` populated →
 *       renders ``water_bodies[0]`` values.
 *   (c) top-level empty + multiple ``water_bodies`` populated →
 *       primary block renders body[0]; additional bodies render in
 *       their own cards via the existing hybrid layout (per-body
 *       policy — noted in the commit).
 *   (d) both empty → renders the existing "No chemistry recorded"
 *       empty-state copy.
 *
 * Plus one edge:
 *   (e) top-level chemicals ALL have amount=0 → falls back to
 *       ``water_bodies[0]`` per ruling #3 ("0-amount entries as
 *       empty for fallback purposes").  0-value readings stay
 *       meaningful (0 ppm chlorine is a valid measurement).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";


const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: { get: (...a) => getSpy(...a), post: vi.fn(),
           patch: vi.fn(), del: vi.fn() },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ id: "sr-1" }),
}));

vi.mock("@/theme", () => {
  // DTP-2 · Feb-2026 — expose portalColors + portalGradients so
  // pages migrated in the sweep resolve their imports.
  const base = {
    brand: "#0B4A6F", onBrand: "#FFFFFF", onSurface: "#111827",
    onSurfaceSecondary: "#6B7280", muted: "#6B7280", border: "#E5E7EB",
    divider: "#E5E7EB", surface: "#FFFFFF", surfaceSecondary: "#F8FAFC",
    success: "#059669",
  };
  return {
    colors: base,
    portalColors: base,
    portalGradients: { navyToBlue: { css: "linear-gradient(#000,#111)" } },
    money: (n) => `$${Number(n || 0).toFixed(2)}`,
  };
});

// eslint-disable-next-line import/first
import { PortalServiceReportDetail } from "@/pages/portal/PortalServiceReports";


function _baseReport(overrides = {}) {
  return {
    id: "sr-1",
    job: { id: "job-1", title: "Weekly pool service",
             service_type: "pool_service" },
    status: "submitted",
    template: "pool",
    chemical_readings: [],
    chemicals_added: [],
    checklist_items: [],
    photos: [],
    job_photos: [],
    water_bodies: [],
    submitted_at: "2026-02-11T15:00:00Z",
    ...overrides,
  };
}


beforeEach(() => {
  getSpy.mockReset();
});


// ═══════════════════════════════════════════════════════════════════
// (a) Top-level populated → renders top-level.
// ═══════════════════════════════════════════════════════════════════
describe("PS-B · portal chemicals · top-level populated", () => {
  it("renders top-level values and ignores water_bodies[0]", async () => {
    getSpy.mockResolvedValue(_baseReport({
      chemical_readings: [
        { key: "chlorine", name: "Chlorine", value: 3.0,
          label: "Average" },
      ],
      chemicals_added: [
        { name: "Muriatic Acid", amount: 32, unit: "oz" },
      ],
      // A different body[0] payload — the fallback MUST NOT
      // reach for this when top-level is populated.
      water_bodies: [{
        type: "pool",
        readings: [{ key: "chlorine", value: 999, label: "Elevated" }],
        chemicals_used: [{ name: "SHOULD_NOT_APPEAR",
                              amount: 5, unit: "gal" }],
      }],
    }));
    render(<PortalServiceReportDetail />);
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    // Wait for detail body.
    await screen.findByTestId(
      "portal-service-report-primary-pool",
    );

    // Top-level chemical is rendered.
    const chem0 = screen.getByTestId(
      "portal-service-report-chemical-0",
    );
    expect(chem0.textContent).toMatch(/Muriatic Acid/);
    expect(chem0.textContent).toMatch(/32/);

    // water_bodies[0]'s SHOULD_NOT_APPEAR did NOT bleed through.
    expect(screen.queryByText(/SHOULD_NOT_APPEAR/)).toBeNull();
    // Primary empty state is absent.
    expect(
      screen.queryByTestId(
        "portal-service-report-primary-empty",
      ),
    ).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// (b) Top-level empty + water_bodies[0] populated → renders body[0].
// ═══════════════════════════════════════════════════════════════════
describe("PS-B · portal chemicals · top-level empty, body[0] populated", () => {
  it("falls back to water_bodies[0].chemicals_used + readings", async () => {
    getSpy.mockResolvedValue(_baseReport({
      chemical_readings: [],
      chemicals_added: [],
      water_bodies: [{
        type: "pool",
        readings: [
          { key: "chlorine", name: "Chlorine", value: 2.5,
            label: "Average" },
        ],
        chemicals_used: [
          { name: "Cal Hypo", amount: 8, unit: "oz" },
          { name: "Cyanuric Acid", amount: 4, unit: "oz" },
        ],
      }],
    }));
    render(<PortalServiceReportDetail />);
    await screen.findByTestId(
      "portal-service-report-primary-pool",
    );

    // Body[0] chemicals surface in the primary block.
    const chem0 = screen.getByTestId(
      "portal-service-report-chemical-0",
    );
    expect(chem0.textContent).toMatch(/Cal Hypo/);
    expect(chem0.textContent).toMatch(/8/);
    const chem1 = screen.getByTestId(
      "portal-service-report-chemical-1",
    );
    expect(chem1.textContent).toMatch(/Cyanuric Acid/);

    // Readings also fell back.
    expect(screen.getByTestId(
      "portal-service-report-readings-list",
    )).toBeInTheDocument();
    // Empty-state absent.
    expect(screen.queryByTestId(
      "portal-service-report-primary-empty",
    )).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// (c) Top-level empty + multiple water_bodies populated →
// primary shows body[0]; body[1]+ render in their own cards.
// ═══════════════════════════════════════════════════════════════════
describe("PS-B · portal chemicals · top-level empty, multiple bodies", () => {
  it("primary renders body[0]; additional bodies render in own cards", async () => {
    getSpy.mockResolvedValue(_baseReport({
      chemical_readings: [],
      chemicals_added: [],
      water_bodies: [
        {
          type: "pool", name: "Main pool",
          readings: [
            { key: "chlorine", value: 3, label: "Average" },
          ],
          chemicals_used: [
            { name: "POOL_CHEM", amount: 2, unit: "gal" },
          ],
        },
        {
          type: "spa", name: "Backyard spa",
          readings: [
            { key: "chlorine", value: 4, label: "Average" },
          ],
          chemicals_used: [
            { name: "SPA_CHEM", amount: 1, unit: "cup" },
          ],
        },
      ],
    }));
    render(<PortalServiceReportDetail />);
    await screen.findByTestId(
      "portal-service-report-primary-pool",
    );

    // Primary block shows body[0]'s POOL_CHEM.
    const primaryChem = screen.getByTestId(
      "portal-service-report-chemical-0",
    );
    expect(primaryChem.textContent).toMatch(/POOL_CHEM/);
    // POOL_CHEM appears ONCE (primary only, not duplicated in body[0]'s card).
    const poolMatches = screen.getAllByText(/POOL_CHEM/);
    expect(poolMatches.length).toBe(1);

    // Additional bodies section renders (body[1] card exists).
    expect(screen.getByTestId(
      "portal-service-report-water-bodies",
    )).toBeInTheDocument();
    expect(screen.getByTestId(
      "portal-service-report-body-0",
    )).toBeInTheDocument();  // additionalBodies[0] === water_bodies[1]

    // Body[1]'s SPA_CHEM is visible in its own card, not in
    // the primary block.
    expect(screen.getByTestId(
      "portal-service-report-body-0-chemical-0",
    ).textContent).toMatch(/SPA_CHEM/);
  });
});


// ═══════════════════════════════════════════════════════════════════
// (d) Both empty → "No chemistry recorded".
// ═══════════════════════════════════════════════════════════════════
describe("PS-B · portal chemicals · both empty", () => {
  it("renders 'No chemistry recorded' empty state", async () => {
    getSpy.mockResolvedValue(_baseReport({
      chemical_readings: [],
      chemicals_added: [],
      water_bodies: [{
        type: "pool", readings: [], chemicals_used: [],
      }],
    }));
    render(<PortalServiceReportDetail />);
    const empty = await screen.findByTestId(
      "portal-service-report-primary-empty",
    );
    expect(empty.textContent).toMatch(/No chemistry recorded/);
    expect(screen.queryByTestId(
      "portal-service-report-readings-list",
    )).toBeNull();
    expect(screen.queryByTestId(
      "portal-service-report-chemicals-block",
    )).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// (e) Top-level all 0-amount → falls back to body[0].
// ═══════════════════════════════════════════════════════════════════
describe("PS-B · portal chemicals · top-level 0-amount", () => {
  it("treats 0-amount top-level chemicals as empty and falls back", async () => {
    getSpy.mockResolvedValue(_baseReport({
      chemical_readings: [],
      chemicals_added: [
        // Both entries are 0-amount (autogen chem tags with no
        // actual dosing).  Ruling #3: fall back.
        { name: "Chlorine", amount: 0, unit: "gal" },
        { name: "Acid", amount: 0, unit: "gal" },
      ],
      water_bodies: [{
        type: "pool",
        readings: [],
        chemicals_used: [
          { name: "REAL_DOSE", amount: 2, unit: "gal" },
        ],
      }],
    }));
    render(<PortalServiceReportDetail />);
    await screen.findByTestId(
      "portal-service-report-primary-pool",
    );

    // Fallback rendered — REAL_DOSE from body[0] is present.
    expect(screen.getByTestId(
      "portal-service-report-chemical-0",
    ).textContent).toMatch(/REAL_DOSE/);
    // Top-level 0-amount entries are NOT rendered (they were
    // rejected by the fallback-decision filter and body[0] took
    // over).
    expect(screen.queryByText(/^Chlorine$/)).toBeNull();
  });

  it("does NOT fall back when at least one top-level chemical has non-zero amount", async () => {
    // A partially filled top-level entry (one non-zero amount, one
    // 0-amount) still renders top-level per ruling #3 ("Do NOT
    // trigger fallback on non-zero amounts even if some fields
    // are blank").
    getSpy.mockResolvedValue(_baseReport({
      chemical_readings: [],
      chemicals_added: [
        { name: "Chlorine", amount: 0, unit: "gal" },
        { name: "PARTIAL_DOSE", amount: 3, unit: "gal" },
      ],
      water_bodies: [{
        type: "pool",
        readings: [],
        chemicals_used: [
          { name: "SHOULD_NOT_APPEAR", amount: 9, unit: "gal" },
        ],
      }],
    }));
    render(<PortalServiceReportDetail />);
    await screen.findByTestId(
      "portal-service-report-primary-pool",
    );
    // Top-level partial-entry set is rendered — PARTIAL_DOSE
    // present, SHOULD_NOT_APPEAR (body) absent.
    expect(screen.queryByText(/PARTIAL_DOSE/)).toBeInTheDocument();
    expect(screen.queryByText(/SHOULD_NOT_APPEAR/)).toBeNull();
  });
});
