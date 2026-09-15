/**
 * Phase CHEM4 · Feb-2026 — Hybrid Pool + additional-body layout.
 *
 * Verifies the customer portal report detail:
 *   * Flat "Pool" block at the top sourced from the report's
 *     TOP-LEVEL ``chemical_readings`` + ``chemicals_added`` — always
 *     renders (with a truthful empty-state if both surfaces are
 *     empty).
 *   * Additional bodies (index 1+) render below in their own cards
 *     with per-body chemistry + chemicals.
 *   * Primary pool is NEVER duplicated between the flat block and a
 *     card.
 *   * Card titles use the canonical ``BODY_TYPE_LABELS`` map from
 *     ``lib/waterBodies``; unknown body types fall back to the raw
 *     slug.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, within } from "@testing-library/react";

const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => getMock(...a) },
}));

const TEST_SR = "sr-chem4-hybrid";
vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: TEST_SR }),
  useNavigate: () => vi.fn(),
  Link: ({ to, children, ...p }) => <a href={to} {...p}>{children}</a>,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { PortalServiceReportDetail } from "@/pages/portal/PortalServiceReports";


function mkSr(overrides = {}) {
  return {
    id: TEST_SR, job_id: "j-1",
    submitted_at: "2025-11-04T15:30:00Z",
    template: "pool",
    chemical_readings: [
      { key: "free_chlorine",  value: 2.5 },
      { key: "ph",             value: 7.4 },
      { key: "alkalinity",     value: 90 },
      { key: "cyanuric_acid",  value: 45 },
    ],
    chemicals_added: [
      { name: "Liquid Chlorine",  amount: 32, unit: "oz" },
    ],
    checklist_items: [],
    photos: [],
    notes: "",
    ...overrides,
  };
}


beforeEach(() => { getMock.mockReset(); });
afterEach(() => cleanup());


describe("Phase CHEM4 · PortalServiceReportDetail · hybrid layout", () => {
  it("no water_bodies → flat Pool block only, no cards", async () => {
    getMock.mockResolvedValueOnce(mkSr({ water_bodies: [] }));
    render(<PortalServiceReportDetail />);
    // Flat block renders.
    expect(
      await screen.findByTestId("portal-service-report-primary-pool"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("portal-service-report-readings-list"),
    ).toBeTruthy();
    // No additional-body card wrapper.
    expect(
      screen.queryByTestId("portal-service-report-water-bodies"),
    ).toBeNull();
    expect(screen.queryByTestId("portal-service-report-body-0")).toBeNull();
  });

  it("water_bodies=[primary_pool only] → flat Pool block only, no cards", async () => {
    getMock.mockResolvedValueOnce(mkSr({
      water_bodies: [
        { id: "wb-1", type: "pool", label: "Main Pool", readings: [] },
      ],
    }));
    render(<PortalServiceReportDetail />);
    expect(
      await screen.findByTestId("portal-service-report-primary-pool"),
    ).toBeTruthy();
    // The primary is index 0 → skipped. No cards.
    expect(
      screen.queryByTestId("portal-service-report-water-bodies"),
    ).toBeNull();
    expect(screen.queryByTestId("portal-service-report-body-0")).toBeNull();
  });

  it("primary Pool + Spa → flat block PLUS one Spa card", async () => {
    getMock.mockResolvedValueOnce(mkSr({
      water_bodies: [
        { id: "wb-1", type: "pool", label: "Main Pool", readings: [] },
        {
          id: "wb-2", type: "spa", label: "Spa",
          readings: [
            { key: "free_chlorine", value: 2.0 },
            { key: "ph",            value: 7.5 },
          ],
          chemicals_used: [
            { name: "Alkalinity Increaser", amount: 6, unit: "oz" },
          ],
        },
      ],
    }));
    render(<PortalServiceReportDetail />);
    // Flat Pool block still present + fed from top-level readings.
    expect(
      await screen.findByTestId("portal-service-report-primary-pool"),
    ).toBeTruthy();
    // Exactly one additional-body card, and its badge is "Spa".
    const wb = screen.getByTestId("portal-service-report-water-bodies");
    const card = within(wb).getByTestId("portal-service-report-body-0");
    expect(within(card).getByTestId("portal-service-report-body-badge-0").textContent).toBe("Spa");
    // Per-body chemistry + chemicals sub-blocks rendered.
    expect(
      within(card).getByTestId("portal-service-report-body-readings-0"),
    ).toBeTruthy();
    expect(
      within(card).getByTestId("portal-service-report-body-chemicals-0"),
    ).toBeTruthy();
    // No second card.
    expect(within(wb).queryByTestId("portal-service-report-body-1")).toBeNull();
  });

  it("primary + Spa + Fountain → flat block + Spa card + Fountain card, in order", async () => {
    getMock.mockResolvedValueOnce(mkSr({
      water_bodies: [
        { id: "wb-1", type: "pool",     label: "Main Pool", readings: [] },
        {
          id: "wb-2", type: "spa",      label: "Spa",
          readings: [{ key: "free_chlorine", value: 3.0 }],
        },
        {
          id: "wb-3", type: "fountain", label: "Front Fountain",
          readings: [{ key: "ph", value: 7.6 }],
        },
      ],
    }));
    render(<PortalServiceReportDetail />);
    await screen.findByTestId("portal-service-report-primary-pool");
    const wb = screen.getByTestId("portal-service-report-water-bodies");
    const card0 = within(wb).getByTestId("portal-service-report-body-0");
    const card1 = within(wb).getByTestId("portal-service-report-body-1");
    // Card 0 = Spa, Card 1 = Fountain (order preserved from index 1+).
    expect(within(card0).getByTestId("portal-service-report-body-badge-0").textContent).toBe("Spa");
    expect(within(card1).getByTestId("portal-service-report-body-badge-1").textContent).toBe("Fountain");
    // Section title reflects "2 additional bodies of water".
    expect(wb.textContent).toContain("2 additional bodies of water");
  });

  it("additional body with empty chemistry AND chemicals → header renders, sub-block absent", async () => {
    getMock.mockResolvedValueOnce(mkSr({
      water_bodies: [
        { id: "wb-1", type: "pool", label: "Main Pool", readings: [] },
        {
          id: "wb-2", type: "spa", label: "Spa",
          readings: [], chemicals_used: [],
        },
      ],
    }));
    render(<PortalServiceReportDetail />);
    const card = await screen.findByTestId("portal-service-report-body-0");
    // Header (badge) still renders — customer needs to know the body was serviced.
    expect(within(card).getByTestId("portal-service-report-body-badge-0").textContent).toBe("Spa");
    // Sub-blocks NOT rendered.
    expect(
      within(card).queryByTestId("portal-service-report-body-readings-0"),
    ).toBeNull();
    expect(
      within(card).queryByTestId("portal-service-report-body-chemicals-0"),
    ).toBeNull();
  });

  it("unknown body_type falls back to the raw slug in the card title", async () => {
    getMock.mockResolvedValueOnce(mkSr({
      water_bodies: [
        { id: "wb-1", type: "pool", label: "Main Pool", readings: [] },
        {
          id: "wb-2", type: "koi_pond",   // NOT in BODY_TYPE_LABELS
          readings: [{ key: "ph", value: 7.4 }],
        },
      ],
    }));
    render(<PortalServiceReportDetail />);
    const card = await screen.findByTestId("portal-service-report-body-0");
    // Falls back to the raw slug verbatim (design intent: no invented labels).
    expect(within(card).getByTestId("portal-service-report-body-badge-0").textContent).toBe("koi_pond");
  });

  it("flat block renders truthful empty-state when top-level surfaces are empty", async () => {
    getMock.mockResolvedValueOnce(mkSr({
      chemical_readings: [],
      chemicals_added: [],
      water_bodies: [
        { id: "wb-1", type: "pool", label: "Main Pool", readings: [] },
      ],
    }));
    render(<PortalServiceReportDetail />);
    const primary = await screen.findByTestId(
      "portal-service-report-primary-pool",
    );
    // Empty-state row present — section is not invisible.
    expect(
      within(primary).getByTestId("portal-service-report-primary-empty"),
    ).toBeTruthy();
    expect(primary.textContent).toContain("No chemistry recorded");
    // Readings list NOT rendered when top-level readings are empty.
    expect(
      screen.queryByTestId("portal-service-report-readings-list"),
    ).toBeNull();
  });

  it("primary pool is NEVER duplicated between flat block and a card", async () => {
    getMock.mockResolvedValueOnce(mkSr({
      water_bodies: [
        {
          id: "wb-1", type: "pool", label: "Main Pool",
          // If the code accidentally rendered index 0 as a card, we'd
          // see this reading a second time.
          readings: [{ key: "free_chlorine", value: 999 }],
        },
        {
          id: "wb-2", type: "spa", label: "Spa",
          readings: [{ key: "free_chlorine", value: 2.0 }],
        },
      ],
    }));
    render(<PortalServiceReportDetail />);
    await screen.findByTestId("portal-service-report-primary-pool");
    // Only ONE body card should appear — the Spa (index 1).
    expect(screen.getByTestId("portal-service-report-body-0")).toBeTruthy();
    expect(screen.queryByTestId("portal-service-report-body-1")).toBeNull();
    // Body-0 card badge is "Spa", not "Pool".
    expect(
      screen.getByTestId("portal-service-report-body-badge-0").textContent,
    ).toBe("Spa");
  });
});
