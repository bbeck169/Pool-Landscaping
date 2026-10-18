/**
 * TD-69 (web b86ecb289) — portal service-type resolver + chemistry gating.
 * TD-74 (web 44734f597) no-op guard — mobile portal home hero never had
 * the "NEXT VISIT" overlay.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, waitFor } from "@testing-library/react-native";

import { resolveServiceType } from "@/src/lib/portalServiceType";
import { api } from "@/src/api";
import PortalServiceReports from "@/app/portal/service-reports";
import PortalServiceReportDetail from "@/app/portal/service-report/[id]";

jest.mock("@/src/api", () => ({
  api: { get: jest.fn() },
  api_base: () => "https://be.test/api",
  getAuthToken: jest.fn(async () => "tok"),
}));
jest.mock("expo-router", () => {
  const React = jest.requireActual("react");
  return {
    useFocusEffect: (cb: any) => React.useEffect(cb, [cb]),
    useLocalSearchParams: () => ({ id: "sr1" }),
    useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  };
});
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));
jest.mock("@/src/components/interactive", () => ({ ClickableAddress: () => null }));

describe("resolveServiceType (web contract)", () => {
  it.each([
    [{ template: "pool", job: { service_type: "Landscaping" } }, "landscape"], // operator-reported bug
    [{ template: "pool_service", service_line: "lawn care" }, "landscape"],
    [{ service_category: "Yard cleanup" }, "landscape"],
    [{ job: { service_line: "Garden" } }, "landscape"],
    [{ job: { service_category: "MOWING" } }, "landscape"],
    [{ template: "pool" }, "pool"],
    [{ service_type: "Spa repair" }, "pool"],
    [{ template: "water_care" }, "pool"],
    [{ job: { service_type: "Chemical check" } }, "pool"],
    [{ service_type: "Gutter clean" }, "generic"],
    [{}, "generic"],
    [null, "generic"],
    [{ template: 42, service_type: null }, "generic"],
  ])("%j → %s", (rec, expected) => {
    expect(resolveServiceType(rec)).toBe(expected);
  });
});

beforeEach(() => (api.get as jest.Mock).mockReset());

it("SR list: landscape job with a pool-ish template shows the Landscape badge", async () => {
  (api.get as jest.Mock).mockResolvedValue([
    { id: "r1", job_title: "Front yard", template: "pool", job: { service_type: "Landscaping" },
      submitted_at: "2026-08-27T10:00:00Z" },
  ]);
  const q = render(<PortalServiceReports />);
  await waitFor(() => q.getByTestId("portal-service-reports-item-r1"));
  expect(q.getByText("Landscape service")).toBeTruthy();
  expect(q.queryByText("Pool service")).toBeNull();
});

const MULTI_BODY_SR = {
  id: "sr1", submitted_at: "2026-08-27T10:00:00Z",
  chemical_readings: [{ key: "ph", name: "pH", value: 7.4 }],
  chemicals_added: [{ name: "Muriatic Acid", quantity: 0.5 }],
  water_bodies: [
    { id: "b1", type: "pool", name: "Pool", readings: [{ key: "ph", value: 7.4 }] },
    { id: "b2", type: "spa", name: "Spa", readings: [{ key: "ph", value: 7.6 }] },
  ],
};

it("SR detail: landscape report hides ALL chemistry incl. multi-body block", async () => {
  (api.get as jest.Mock).mockResolvedValue({
    ...MULTI_BODY_SR, template: "pool", job: { title: "Yard", service_type: "Landscape Maintenance" },
  });
  const q = render(<PortalServiceReportDetail />);
  await waitFor(() => q.getByTestId("portal-page-shell-card"));
  expect(q.queryByTestId("portal-water-bodies-section")).toBeNull();
  expect(q.queryByTestId("portal-service-report-readings")).toBeNull();
  expect(q.queryByTestId("portal-service-report-chemicals")).toBeNull();
});

it("SR detail: pool report still renders multi-body chemistry", async () => {
  (api.get as jest.Mock).mockResolvedValue({
    ...MULTI_BODY_SR, template: "pool", job: { title: "Pool", service_type: "Pool Cleaning" },
  });
  const q = render(<PortalServiceReportDetail />);
  await waitFor(() => q.getByTestId("portal-water-bodies-section"));
  expect(q.getByTestId("portal-service-report-chemicals")).toBeTruthy();
});

it("TD-74 no-op: portal home has no NEXT VISIT overlay", () => {
  const src = fs.readFileSync(path.join(__dirname, "../app/portal/home.tsx"), "utf8");
  expect(src).not.toMatch(/next_visit|next visit/i);
});
