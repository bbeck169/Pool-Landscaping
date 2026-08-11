/**
 * Feb-2026 · Checklist reclassifier — web PoolChecklistForm empty-state picker.
 *
 * Guards the Chemical Readings section against silently rendering an
 * empty state when the underlying report is classified as
 * ``template === "generic"``. The picker offers Pool / Landscape /
 * Other quick-set buttons that PATCH the job's ``service_type`` and
 * bubble the re-fetch via the injected ``onReclassify`` callback.
 *
 * Explicit invariants covered:
 *   1. ``readingFields=[]`` + ``template="generic"`` → picker visible.
 *   2. ``readingFields=[]`` + ``template="pool"``    → picker hidden
 *      (tenant misconfig — different bug, must not mask).
 *   3. Read-only fallback ("Ask an admin…") when
 *      ``canEditServiceType=false``.
 *   4. Clicking a picker button invokes ``onReclassify(value)`` with
 *      the expected service-type string.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// The component internally hits /service-reports/last-readings on
// mount; stub the api layer so the test doesn't need a network.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async () => ({ readings: {}, recent_readings: {} })),
    post: vi.fn(async () => ({ recommendations: [] })),
  },
}));

import PoolChecklistForm from "@/components/checklist/PoolChecklistForm";

const baseProps = {
  jobId: "job-1",
  customerId: "cust-1",
  locked: false,
  readings: [],
  chemicalsAdded: [],
  chemicalsCatalog: [],
  chemicalUnits: ["gal", "lbs", "oz", "tabs"],
  checklistItems: [],
  notes: "",
  observations: {},
  onChange: () => {},
};

describe("PoolChecklistForm · Chemical Readings reclassify picker", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders the picker when readingFields=[] and template='generic'", () => {
    const onReclassify = vi.fn(async () => {});
    render(
      <PoolChecklistForm
        {...baseProps}
        readingFields={[]}
        template="generic"
        canEditServiceType={true}
        onReclassify={onReclassify}
      />,
    );
    expect(screen.getByTestId("pool-service-type-picker-block")).toBeTruthy();
    expect(screen.getByTestId("pool-service-type-picker")).toBeTruthy();
    expect(screen.getByTestId("pool-service-type-set-pool-service")).toBeTruthy();
    expect(screen.getByTestId("pool-service-type-set-landscape-service")).toBeTruthy();
    expect(screen.getByTestId("pool-service-type-set-other")).toBeTruthy();
  });

  it("HIDES the picker when template='pool' (tenant misconfig case)", () => {
    const onReclassify = vi.fn(async () => {});
    render(
      <PoolChecklistForm
        {...baseProps}
        readingFields={[]}
        template="pool"
        canEditServiceType={true}
        onReclassify={onReclassify}
      />,
    );
    expect(screen.queryByTestId("pool-service-type-picker-block")).toBeNull();
    expect(screen.queryByTestId("pool-service-type-picker")).toBeNull();
  });

  it("shows read-only hint when canEditServiceType=false", () => {
    render(
      <PoolChecklistForm
        {...baseProps}
        readingFields={[]}
        template="generic"
        canEditServiceType={false}
        onReclassify={() => {}}
      />,
    );
    expect(screen.getByTestId("pool-service-type-picker-block")).toBeTruthy();
    expect(screen.getByTestId("pool-service-type-readonly-hint")).toBeTruthy();
    expect(screen.queryByTestId("pool-service-type-picker")).toBeNull();
  });

  it("HIDES the picker once readingFields populate (post-reclassify state)", () => {
    render(
      <PoolChecklistForm
        {...baseProps}
        readingFields={[
          { key: "chlorine", name: "Free Chlorine", unit: "ppm", type: "select",
            min: 0, max: 20, step: 0.1, options: ["0.0", "1.0", "2.0"] },
        ]}
        template="pool"
        canEditServiceType={true}
        onReclassify={() => {}}
      />,
    );
    expect(screen.queryByTestId("pool-service-type-picker-block")).toBeNull();
  });

  it("invokes onReclassify('Pool Service') when the Pool button is clicked", async () => {
    const onReclassify = vi.fn(async () => {});
    render(
      <PoolChecklistForm
        {...baseProps}
        readingFields={[]}
        template="generic"
        canEditServiceType={true}
        onReclassify={onReclassify}
      />,
    );
    fireEvent.click(screen.getByTestId("pool-service-type-set-pool-service"));
    await waitFor(() => expect(onReclassify).toHaveBeenCalledTimes(1));
    expect(onReclassify).toHaveBeenCalledWith("Pool Service");
  });
});
