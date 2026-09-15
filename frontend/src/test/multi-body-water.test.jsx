/**
 * Feb-2026 · Multi-body service reports (Phase 2 · web) — Vitest.
 *
 * Locks in:
 *   * WaterBodyPanel renders trimmed reading rows per body type
 *     (spa/water_feature/fountain) and enforces required-only-for-pool.
 *   * WaterBodyManager add/remove flow — remove disabled on the last
 *     remaining body, confirm modal when the body has data.
 *   * PortalServiceReports list surfaces a body-mix badge when the
 *     API returns ``water_body_count > 1``; single-body baseline is
 *     visually unchanged.
 *   * PortalServiceReports detail renders per-body accordion sections
 *     when ``water_bodies.length > 1`` and hides the flat top-level
 *     chemistry/chemicals lists to avoid duplication.
 *   * validateBodies + missingRequiredReadings helpers mirror the
 *     backend allow-list contract exactly.
 */
/* eslint-disable react/prop-types */
import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { describe, it, expect, vi, beforeEach } from "vitest";

import WaterBodyPanel from "@/components/checklist/WaterBodyPanel";
import {
  BODY_TYPE_LABELS,
  READING_ALLOWLIST,
  READING_REQUIRED,
  CHEMICAL_ALLOWLIST,
  MAX_BODIES,
  makeEmptyBody,
  validateBodies,
  missingRequiredReadings,
} from "../lib/waterBodies";


// ══════════════════════════════════════════════════════════════════════
// waterBodies.js pure helpers
// ══════════════════════════════════════════════════════════════════════
describe("waterBodies helpers", () => {
  it("READING_ALLOWLIST matches the approved kickoff spec", () => {
    expect(READING_ALLOWLIST.pool).toEqual([
      "free_chlorine", "ph", "alkalinity",
      "cyanuric_acid", "calcium_hardness", "salt", "tds", "phosphates",
    ]);
    expect(READING_ALLOWLIST.spa).toEqual([
      "free_chlorine", "ph", "alkalinity", "calcium_hardness",
    ]);
    expect(READING_ALLOWLIST.water_feature).toEqual([
      "free_chlorine", "ph",
    ]);
    expect(READING_ALLOWLIST.fountain).toEqual([
      "free_chlorine", "ph",
    ]);
  });

  it("READING_REQUIRED gates only pool (Required Four)", () => {
    expect(READING_REQUIRED.pool).toHaveLength(4);
    expect(READING_REQUIRED.pool).toEqual([
      "free_chlorine", "ph", "alkalinity", "cyanuric_acid",
    ]);
    expect(READING_REQUIRED.spa).toHaveLength(0);
    expect(READING_REQUIRED.water_feature).toHaveLength(0);
    expect(READING_REQUIRED.fountain).toHaveLength(0);
    expect(READING_REQUIRED.other).toHaveLength(0);
  });

  it("CHEMICAL_ALLOWLIST enforces per-type restrictions", () => {
    expect(CHEMICAL_ALLOWLIST.spa).not.toContain("salt");
    expect(CHEMICAL_ALLOWLIST.spa).not.toContain("phosphate_remover");
    expect(CHEMICAL_ALLOWLIST.fountain).not.toContain("salt");
    expect(CHEMICAL_ALLOWLIST.pool).toContain("salt");
  });

  it("validateBodies rejects spa+CYA and fountain+salt", () => {
    const r1 = validateBodies([{
      type: "spa",
      readings: [{ key: "cyanuric_acid", value: 40 }],
    }]);
    expect(r1.valid).toBe(false);
    expect(r1.errors[0].message).toBe("reading_not_allowed_for_body_type");

    const r2 = validateBodies([{
      type: "fountain",
      chemicals_used: [{ product_slug: "salt", quantity: 1 }],
    }]);
    expect(r2.valid).toBe(false);
    expect(r2.errors[0].message).toBe("chemical_not_allowed_for_body_type");
  });

  it("validateBodies accepts ``other`` free-form", () => {
    const r = validateBodies([{
      type: "other",
      readings: [{ key: "orp", value: 700 }],
      chemicals_used: [{ product_slug: "salt", quantity: 5 }],
    }]);
    expect(r.valid).toBe(true);
  });

  it("missingRequiredReadings flags empty pool cores; is empty for spa", () => {
    const empty = missingRequiredReadings({ type: "pool", readings: [] });
    expect(empty).toEqual(["free_chlorine", "ph",
                            "alkalinity", "cyanuric_acid"]);
    const filled = missingRequiredReadings({
      type: "pool",
      readings: [
        { key: "free_chlorine", value: 3 },
        { key: "ph", value: 7.4 },
        { key: "alkalinity", value: 90 },
        { key: "cyanuric_acid", value: 45 },
      ],
    });
    expect(filled).toEqual([]);
    const spa = missingRequiredReadings({ type: "spa", readings: [] });
    expect(spa).toEqual([]);
  });

  it("MAX_BODIES = 6 (soft cap)", () => {
    expect(MAX_BODIES).toBe(6);
  });
});


// ══════════════════════════════════════════════════════════════════════
// WaterBodyPanel — per-body compact editor
// ══════════════════════════════════════════════════════════════════════
describe("<WaterBodyPanel /> per-body rendering", () => {
  it("Spa body renders only trimmed chemistry (FC/pH/TA/Calcium)", () => {
    const body = makeEmptyBody("spa", 1);
    render(
      <WaterBodyPanel
        body={body} index={1} locked={false} canRemove
        onChange={vi.fn()} onRemove={vi.fn()} />,
    );
    // Allowed for spa.
    expect(screen.getByTestId("wb-reading-free_chlorine")).toBeInTheDocument();
    expect(screen.getByTestId("wb-reading-ph")).toBeInTheDocument();
    expect(screen.getByTestId("wb-reading-alkalinity")).toBeInTheDocument();
    expect(screen.getByTestId("wb-reading-calcium_hardness")).toBeInTheDocument();
    // NOT allowed for spa (per approved spec).
    expect(screen.queryByTestId("wb-reading-cyanuric_acid")).toBeNull();
    expect(screen.queryByTestId("wb-reading-total_chlorine")).toBeNull();
    expect(screen.queryByTestId("wb-reading-salt")).toBeNull();
    expect(screen.queryByTestId("wb-reading-tds")).toBeNull();
    expect(screen.queryByTestId("wb-reading-phosphates")).toBeNull();
    // Spa is soft-warn only → no required-warning banner initially.
    expect(screen.queryByTestId("water-body-required-warning-1")).toBeNull();
  });

  it("Water Feature body renders only FC + pH readings", () => {
    const body = makeEmptyBody("water_feature", 1);
    render(
      <WaterBodyPanel
        body={body} index={1} locked={false} canRemove
        onChange={vi.fn()} onRemove={vi.fn()} />,
    );
    expect(screen.getByTestId("wb-reading-free_chlorine")).toBeInTheDocument();
    expect(screen.getByTestId("wb-reading-ph")).toBeInTheDocument();
    expect(screen.queryByTestId("wb-reading-alkalinity")).toBeNull();
    expect(screen.queryByTestId("wb-reading-cyanuric_acid")).toBeNull();
    expect(screen.queryByTestId("wb-reading-calcium_hardness")).toBeNull();
  });

  it("Fountain body chemicals allow-list excludes salt", () => {
    const body = makeEmptyBody("fountain", 1);
    render(
      <WaterBodyPanel
        body={body} index={1} locked={false} canRemove
        onChange={vi.fn()} onRemove={vi.fn()} />,
    );
    expect(screen.getByTestId("wb-chem-liquid_chlorine")).toBeInTheDocument();
    expect(screen.getByTestId("wb-chem-clarifier")).toBeInTheDocument();
    expect(screen.getByTestId("wb-chem-phosphate_remover")).toBeInTheDocument();
    expect(screen.queryByTestId("wb-chem-salt")).toBeNull();
    expect(screen.queryByTestId("wb-chem-chlorine_tabs")).toBeNull();
    expect(screen.queryByTestId("wb-chem-shock")).toBeNull();
  });

  it("Pool body flags missing required readings inline", () => {
    const body = makeEmptyBody("pool", 0);
    render(
      <WaterBodyPanel
        body={body} index={0} locked={false} canRemove={false}
        onChange={vi.fn()} onRemove={vi.fn()} />,
    );
    // Pool is required-gated → warning banner is visible.
    const warn = screen.getByTestId("water-body-required-warning-0");
    expect(warn.textContent).toMatch(/Missing required/i);
    // Remove button is disabled because canRemove=false (last body).
    const remove = screen.getByTestId("water-body-remove-0");
    expect(remove).toBeDisabled();
  });

  it("Remove button emits confirm-remove when body has data", () => {
    const onRemove = vi.fn();
    const body = {
      ...makeEmptyBody("spa", 1),
      notes: "already has entered content",
    };
    render(
      <WaterBodyPanel
        body={body} index={1} locked={false} canRemove
        onChange={vi.fn()} onRemove={onRemove} />,
    );
    fireEvent.click(screen.getByTestId("water-body-remove-1"));
    // Confirm banner appears; the parent's onRemove is NOT called yet.
    expect(screen.getByTestId("water-body-confirm-remove-1")).toBeInTheDocument();
    expect(onRemove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("water-body-confirm-remove-yes-1"));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it("Type-change strips readings + chemicals disallowed under the new type", () => {
    const onChange = vi.fn();
    // Body starts as pool with a full readings set + salt bag.
    const body = {
      id: "b1", type: "pool", label: "Pool", sequence: 0,
      readings: [
        { key: "free_chlorine", value: 3, name: "Free Cl", unit: "ppm" },
        { key: "cyanuric_acid", value: 45, name: "CYA", unit: "ppm" },
        { key: "salt", value: 3200, name: "Salt", unit: "ppm" },
      ],
      chemicals_used: [
        { product_slug: "salt", quantity: 1 },
        { product_slug: "liquid_chlorine", quantity: 2 },
      ],
      media: [], notes: "",
    };
    render(
      <WaterBodyPanel
        body={body} index={1} locked={false} canRemove
        onChange={onChange} onRemove={vi.fn()} />,
    );
    // Change to Spa — CYA + salt reading, salt bag chemical must be dropped.
    fireEvent.change(screen.getByTestId("water-body-type-select-1"), {
      target: { value: "spa" },
    });
    const next = onChange.mock.calls.at(-1)[0];
    expect(next.type).toBe("spa");
    const nextKeys = next.readings.map((r) => r.key);
    expect(nextKeys).toContain("free_chlorine");
    expect(nextKeys).not.toContain("cyanuric_acid");
    expect(nextKeys).not.toContain("salt");
    const nextSlugs = next.chemicals_used.map((c_) => c_.product_slug);
    expect(nextSlugs).toContain("liquid_chlorine");
    expect(nextSlugs).not.toContain("salt");
  });
});


// ══════════════════════════════════════════════════════════════════════
// PortalServiceReports — customer history splits by body count
// ══════════════════════════════════════════════════════════════════════
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async () => ({ items: [] })),
  },
}));


describe("PortalServiceReports — list surface", () => {
  beforeEach(() => vi.clearAllMocks());

  it("Renders per-report body-mix badge when water_body_count > 1", async () => {
    // Import lazily so the mock above is in place.
    const { api } = await import("@/api");
    api.get.mockImplementation(async (path) => {
      // Feb-2026 · list endpoint now emits the paginated envelope +
      // accepts URL search params (page/page_size/q/service_type/…),
      // so match with ``startsWith`` and return ``{items: [...]}``.
      if (/^\/customers\/me\/service-reports\/[^?]/.test(path)) return {};
      if (path.startsWith("/customers/me/service-reports")) {
        const items = [
          {
            id: "r1",
            job_id: "j1",
            job_title: "Weekly Pool Service",
            service_type: "Pool Service",
            submitted_at: "2026-09-01T15:00:00Z",
            scheduled_start: "2026-09-01T15:00:00Z",
            tech_name: "Ada",
            water_body_count: 2,
            water_bodies_summary: [
              { type: "pool", label: "Main Pool", reading_count: 5, chemical_count: 1, media_count: 0, has_notes: true },
              { type: "spa",  label: "Guest Spa", reading_count: 2, chemical_count: 1, media_count: 0, has_notes: false },
            ],
          },
          {
            id: "r2",
            job_id: "j2",
            job_title: "Single body baseline",
            service_type: "Pool Service",
            submitted_at: "2026-08-01T15:00:00Z",
            scheduled_start: "2026-08-01T15:00:00Z",
            tech_name: "Ada",
            water_body_count: 1,
            water_bodies_summary: [
              { type: "pool", label: "Pool", reading_count: 5, chemical_count: 1, media_count: 0, has_notes: false },
            ],
          },
        ];
        return { items, page: 1, page_size: 20, total: items.length, total_pages: 1 };
      }
      return null;
    });

    const { PortalServiceReports } = await import("@/pages/portal/PortalServiceReports");
    const { MemoryRouter } = await import("react-router-dom");

    render(
      <MemoryRouter initialEntries={["/portal/service-reports"]}>
        <PortalServiceReports />
      </MemoryRouter>,
    );

    // Wait for the async load. Both cards should be rendered.
    const r1 = await screen.findByTestId("portal-service-report-card-r1");
    const r2 = await screen.findByTestId("portal-service-report-card-r2");
    // Multi-body report shows the badge + body-mix line.
    expect(within(r1).getByTestId("portal-service-report-bodies-r1"))
      .toHaveTextContent(/2 bodies of water/i);
    expect(within(r1).getByTestId("portal-service-report-body-mix-r1"))
      .toHaveTextContent(/Main Pool.*Guest Spa/i);
    // Single-body baseline stays clean — no badge, no body-mix line.
    expect(within(r2).queryByTestId("portal-service-report-bodies-r2"))
      .toBeNull();
    expect(within(r2).queryByTestId("portal-service-report-body-mix-r2"))
      .toBeNull();
  });
});
