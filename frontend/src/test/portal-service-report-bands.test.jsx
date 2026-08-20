/**
 * Feb-2026 · Water-test bands hotfix — portal service-report page.
 *
 * Verifies that the customer-facing portal renders qualitative bands
 * ("Below Average" / "Average" / "Above Average" / "Elevated") in
 * place of raw ppm/pH numbers, and that the Chemicals Used section
 * is untouched.
 *
 * Uses the existing Vitest + React Testing Library harness — same
 * pattern as ``service-report-chemistry-gate.test.jsx``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, within } from "@testing-library/react";

const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => getMock(...a) },
}));

const TEST_SR = "sr-portal-test";
vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: TEST_SR }),
  useNavigate: () => vi.fn(),
  Link: ({ to, children, ...p }) => <a href={to} {...p}>{children}</a>,
}));

// Toasts / sonner (unused here but the page imports it).
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { PortalServiceReportDetail } from "@/pages/portal/PortalServiceReports";


function mkSr(readings, chemicalsAdded = []) {
  return {
    id: TEST_SR, job_id: "j-1",
    submitted_at: "2025-11-04T15:30:00Z",
    template: "pool",
    chemical_readings: readings,
    chemicals_added: chemicalsAdded,
    checklist_items: [],
    photos: [],
    notes: "",
  };
}


beforeEach(() => {
  getMock.mockReset();
});
afterEach(() => cleanup());


describe("PortalServiceReportDetail · water-test bands", () => {
  it("renders 'Average' band for free_chlorine=2.0 and NEVER surfaces 2.0", async () => {
    getMock.mockResolvedValueOnce(mkSr([
      { key: "free_chlorine",  value: 2.0 },
      { key: "total_chlorine", value: 3.0 },
      { key: "ph",             value: 7.4 },
      { key: "alkalinity",     value: 90 },
      { key: "cyanuric_acid",  value: 45 },
    ]));
    render(<PortalServiceReportDetail />);
    const row = await waitFor(
      () => screen.getByTestId("portal-service-report-reading-free_chlorine"),
      { timeout: 2000 },
    );
    // Display label + band chip present.
    expect(within(row).getByText("Free Cl")).toBeTruthy();
    expect(within(row).getByTestId("chem-label-free_chlorine")).toBeTruthy();
    // Raw numeric value MUST NOT be rendered inside the reading row.
    expect(row.textContent).not.toContain("2.0");
    expect(row.textContent).not.toContain("2");
  });

  it("renders 'Elevated' band chip for pH=8.5 without leaking the number", async () => {
    getMock.mockResolvedValueOnce(mkSr([
      { key: "free_chlorine",  value: 2.5 },
      { key: "total_chlorine", value: 3.0 },
      { key: "ph",             value: 8.5 },
      { key: "alkalinity",     value: 90 },
      { key: "cyanuric_acid",  value: 45 },
    ]));
    render(<PortalServiceReportDetail />);
    const row = await waitFor(
      () => screen.getByTestId("portal-service-report-reading-ph"),
      { timeout: 2000 },
    );
    expect(within(row).getByText("pH")).toBeTruthy();
    // Chip label — the ChemChip surface renders the band text.
    expect(row.textContent).toContain("Elevated");
    expect(row.textContent).not.toContain("8.5");
  });

  it("omits optional readings (water_temp) when blank", async () => {
    getMock.mockResolvedValueOnce(mkSr([
      { key: "free_chlorine",  value: 2.5 },
      { key: "total_chlorine", value: 3.0 },
      { key: "ph",             value: 7.4 },
      { key: "alkalinity",     value: 90 },
      { key: "cyanuric_acid",  value: 45 },
      { key: "water_temp",     value: null },
    ]));
    render(<PortalServiceReportDetail />);
    await waitFor(
      () => screen.getByTestId("portal-service-report-reading-free_chlorine"),
      { timeout: 2000 },
    );
    // Blank optional row MUST NOT render (filter in the component
    // drops rows with empty ``value``).
    expect(screen.queryByTestId(
      "portal-service-report-reading-water_temp",
    )).toBeNull();
  });

  it("renders chemicals used with exact numeric amounts (NOT band-ified)", async () => {
    getMock.mockResolvedValueOnce(mkSr(
      [
        { key: "free_chlorine",  value: 2.5 },
        { key: "total_chlorine", value: 3.0 },
        { key: "ph",             value: 7.4 },
        { key: "alkalinity",     value: 90 },
        { key: "cyanuric_acid",  value: 45 },
      ],
      [{ name: "Muriatic Acid", quantity: 0.5, unit: "gal" }],
    ));
    render(<PortalServiceReportDetail />);
    await waitFor(
      () => screen.getByText(/Muriatic Acid/i),
      { timeout: 2000 },
    );
    // Exact quantity + unit surface unchanged.
    expect(screen.getByText(/0\.5/)).toBeTruthy();
    expect(screen.getByText(/gal/i)).toBeTruthy();
  });
});
