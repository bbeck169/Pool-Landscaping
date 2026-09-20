/**
 * Phase A2 · Feb-2026 — Proactive Intelligence · IntelligenceAlerts
 * page: chemistry-upsell row rendering + upsell CTA + reading
 * sequence + category chip filtering.
 *
 * Scope
 * -----
 * 1. Chemistry-upsell rows render the "Create upsell quote" button
 *    with a valid deep-link URL.
 * 2. Clicking the button navigates to
 *    ``/quotes/new?customer_id=…&service_type=…&source=intelligence_alert&alert_id=…``.
 * 3. The reading sequence "4200 → 4400 → 4600 (target 2700-3400 ppm)"
 *    is rendered inside the row.
 * 4. The Chemistry chip filter posts ``category=chemistry_upsell``
 *    to the API and shows only chemistry rows in the response.
 * 5. Non-chemistry rows do NOT render the upsell CTA — belt-and-
 *    braces guard so future categories don't accidentally inherit it.
 *
 * Strategy — ``vi.mock`` on the api client + ``useNavigate``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";


const getMock  = vi.fn();
const postMock = vi.fn();
const navigateMock = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get:  (...args) => getMock(...args),
    post: (...args) => postMock(...args),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff",
    surfaceSecondary: "#F4F4F5",
    border: "#E4E4E7",
    muted: "#71717A",
    onSurface: "#09090B",
    brand: "#0284C7",
    onBrand: "#FFFFFF",
    onBrandPrimary: "#FFFFFF",
  },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});


import IntelligenceAlerts from "@/pages/admin/IntelligenceAlerts";


const _CHEM_ALERT = {
  id:            "alert-chem-1",
  severity:      "recommended",
  category:      "chemistry_upsell",
  title:         "High salt for 3 visits — filter clean recommended",
  body:          "Readings: 4600 / 4400 / 4200 ppm. Target: 2700-3400 ppm.",
  customer_id:   "cust-42",
  job_id:        "job-99",
  created_at:    new Date().toISOString(),
  read_at:       null,
  dismissed_at:  null,
  actor_context: {
    measurement:            "salt",
    direction:              "high",
    readings:               [4600, 4400, 4200],
    visit_ids:              ["v1", "v2", "v3"],
    target_min:             2700,
    target_max:             3400,
    unit:                   "ppm",
    recommended_action:     "filter_clean",
    suggested_service_type: "filter_clean",
  },
};
const _MISSED_ALERT = {
  id:            "alert-missed-1",
  severity:      "urgent",
  category:      "missed_service",
  title:         "Missed service: Robert Blake",
  body:          "Pool Cleaning scheduled 2026-02-14 was not completed",
  customer_id:   "cust-9",
  job_id:        "job-11",
  created_at:    new Date().toISOString(),
  read_at:       null,
  dismissed_at:  null,
  actor_context: {},
};


function _mkResponse(items, unread = items.length) {
  return { items, limit: 25, unread_count: unread, next_before: null };
}


function _render() {
  return render(
    <MemoryRouter>
      <IntelligenceAlerts />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  navigateMock.mockReset();
});

afterEach(() => cleanup());


describe("IntelligenceAlerts · A2 chemistry-upsell row", () => {
  it("renders a 'Create upsell quote' button on chemistry-upsell rows", async () => {
    getMock.mockResolvedValue(_mkResponse([_CHEM_ALERT]));
    _render();
    const cta = await screen.findByTestId("intelligence-alerts-upsell-0");
    expect(cta).toBeInTheDocument();
    expect(cta.textContent).toContain("Create upsell quote");
  });

  it("navigates to the quote-new deep link with all four query params", async () => {
    getMock.mockResolvedValue(_mkResponse([_CHEM_ALERT]));
    _render();
    const cta = await screen.findByTestId("intelligence-alerts-upsell-0");
    fireEvent.click(cta);
    expect(navigateMock).toHaveBeenCalledTimes(1);
    const url = navigateMock.mock.calls[0][0];
    expect(url).toMatch(/^\/quotes\/new\?/);
    // Parse and check every required param — order-agnostic.
    const qs = new URLSearchParams(url.split("?")[1]);
    expect(qs.get("customer_id")).toBe(_CHEM_ALERT.customer_id);
    expect(qs.get("service_type")).toBe(
      _CHEM_ALERT.actor_context.suggested_service_type,
    );
    expect(qs.get("source")).toBe("intelligence_alert");
    expect(qs.get("alert_id")).toBe(_CHEM_ALERT.id);
  });

  it("renders the reading sequence 4200 → 4400 → 4600 (target 2700-3400 ppm)", async () => {
    getMock.mockResolvedValue(_mkResponse([_CHEM_ALERT]));
    _render();
    const seq = await screen.findByTestId("chemistry-reading-sequence");
    // Sequence oldest → newest for left-to-right trend reading.
    expect(screen.getByTestId("chemistry-reading-seq-oldest").textContent)
      .toBe("4200");
    expect(screen.getByTestId("chemistry-reading-seq-newest").textContent)
      .toBe("4600");
    expect(seq.textContent).toContain("4400");
    // Target band chip is present, includes both bounds + unit.
    const band = screen.getByTestId("chemistry-reading-target-band");
    expect(band.textContent).toContain("2700");
    expect(band.textContent).toContain("3400");
    expect(band.textContent).toContain("ppm");
  });

  it("does NOT render the upsell CTA for non-chemistry rows", async () => {
    getMock.mockResolvedValue(_mkResponse([_MISSED_ALERT]));
    _render();
    // Row itself renders.
    await screen.findByTestId("intelligence-alerts-row-0");
    // No CTA + no reading sequence for a missed-service row.
    expect(screen.queryByTestId("intelligence-alerts-upsell-0")).toBeNull();
    expect(screen.queryByTestId("chemistry-reading-sequence")).toBeNull();
  });
});


describe("IntelligenceAlerts · A2 category filter", () => {
  it("hits ?category=chemistry_upsell when the Chemistry chip is clicked", async () => {
    getMock.mockResolvedValue(_mkResponse([_CHEM_ALERT, _MISSED_ALERT]));
    _render();
    // Wait for first fetch (mount).
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    const chemChip = screen.getByTestId(
      "intelligence-alerts-cat-chemistry_upsell");
    fireEvent.click(chemChip);
    await waitFor(() => {
      // At least one call includes category=chemistry_upsell.
      const call = getMock.mock.calls.find(
        (c) => c[0].includes("category=chemistry_upsell"));
      expect(call).toBeDefined();
    });
  });

  it("renders only chemistry-upsell rows when the API returns that filter", async () => {
    // First call → unfiltered response with 2 alerts.
    getMock.mockResolvedValueOnce(
      _mkResponse([_CHEM_ALERT, _MISSED_ALERT]));
    // Subsequent (after filter click) → only chemistry rows.
    getMock.mockResolvedValue(_mkResponse([_CHEM_ALERT]));
    _render();
    await screen.findByTestId("intelligence-alerts-row-0");
    // Click the chip and confirm the missed-service row is gone.
    fireEvent.click(screen.getByTestId(
      "intelligence-alerts-cat-chemistry_upsell"));
    await waitFor(() => {
      // Only one row remains and it's a chemistry row.
      const row = screen.getByTestId("intelligence-alerts-row-0");
      expect(row.getAttribute("data-category")).toBe("chemistry_upsell");
    });
    expect(screen.queryByTestId("intelligence-alerts-row-1")).toBeNull();
  });
});
