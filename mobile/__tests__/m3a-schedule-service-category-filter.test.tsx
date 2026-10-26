/**
 * M3a · Schedule Service Category filter (web Ticket Y parity).
 * calendar.tsx has no working render harness (k32 / schedule-map-toggle baseline),
 * so the logic lives in lib + hook + component (tested for behaviour here) and the
 * screen wiring is pinned by a source lock.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, fireEvent, renderHook, act, waitFor } from "@testing-library/react-native";

const mockStore: Record<string, string> = {};
jest.mock("@/src/utils/storage", () => ({
  storage: {
    getItem: jest.fn(async (k: string, fb: any) => (k in mockStore ? mockStore[k] : fb)),
    setItem: jest.fn(async (k: string, v: string) => { mockStore[k] = v; return true; }),
    removeItem: jest.fn(async (k: string) => { delete mockStore[k]; return true; }),
  },
}));

import ServiceCategoryChips from "@/src/components/schedule/ServiceCategoryChips";
import { useScheduleServiceCategory } from "@/src/hooks/useScheduleServiceCategory";
import { serviceCategoryParam, canWriteThroughJobs, normalizeServiceCategory, SERVICE_CATEGORY_KEY } from "@/src/lib/scheduleServiceCategory";
import { cachedGet } from "@/src/lib/offline/apiCache";

const mockApiGet = jest.fn();
jest.mock("@/src/api", () => {
  class ApiNetworkError extends Error {}
  return { api: { get: (...a: any[]) => mockApiGet(...a) }, ApiNetworkError };
});

const SRC = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf8");
beforeEach(() => { for (const k of Object.keys(mockStore)) delete mockStore[k]; mockApiGet.mockReset(); });

it("Y1 · chip-group renders All / Pool / Landscaping / Both with the active state on the selected bucket", () => {
  const q = render(<ServiceCategoryChips value="Pool" onChange={jest.fn()} />);
  for (const b of ["all", "pool", "landscaping", "both"]) expect(q.getByTestId(`schedule-service-category-${b}`)).toBeTruthy();
  expect(q.getByTestId("schedule-service-category-pool").props.accessibilityState).toEqual({ selected: true });
  expect(q.getByTestId("schedule-service-category-all").props.accessibilityState).toEqual({ selected: false });
});

it("Y2 · tapping Pool → onChange('Pool'); tapping the active chip is a no-op", () => {
  const onChange = jest.fn();
  const q = render(<ServiceCategoryChips value="All" onChange={onChange} />);
  fireEvent.press(q.getByTestId("schedule-service-category-pool"));
  expect(onChange).toHaveBeenCalledWith("Pool");
  fireEvent.press(q.getByTestId("schedule-service-category-all"));
  expect(onChange).toHaveBeenCalledTimes(1);
});

it("Y3 · query param: Pool → &service_category=pool (lowercase enum, BE normalises); All / junk → no param", () => {
  expect(serviceCategoryParam("Pool")).toBe("&service_category=pool");
  expect(serviceCategoryParam("Landscaping")).toBe("&service_category=landscaping");
  expect(serviceCategoryParam("Both")).toBe("&service_category=both");
  expect(serviceCategoryParam("All")).toBe("");
  expect(serviceCategoryParam("nope")).toBe("");
  expect(normalizeServiceCategory(" POOL ")).toBe("Pool");
});

it("Y4 · composition: crew + category both ship on /jobs (AND), category appended after tech scope", () => {
  expect(SRC).toContain("const jobsUrl = `/jobs?start=${start}&end=${end}${!isTech && crewFiltered ? `&crew_id=${crewFilter}` : \"\"}${techScope}${serviceCategoryParam(serviceCategory)}`;");
  // Evaluate the same template with crew + Pool active.
  const start = "2026-10-19", end = "2026-11-09", isTech = false, crewFiltered = true, crewFilter = "c1", techScope = "";
  const url = `/jobs?start=${start}&end=${end}${!isTech && crewFiltered ? `&crew_id=${crewFilter}` : ""}${techScope}${serviceCategoryParam("Pool")}`;
  expect(url).toBe("/jobs?start=2026-10-19&end=2026-11-09&crew_id=c1&service_category=pool");
});

it("Y5 · cache save SKIPPED when a category filter is active (and still skipped for crew); real cachedGet never calls writeThrough", async () => {
  expect(canWriteThroughJobs({ crewFiltered: false, serviceCategory: "Pool" })).toBe(false);
  expect(canWriteThroughJobs({ crewFiltered: true, serviceCategory: "All" })).toBe(false);
  expect(canWriteThroughJobs({ crewFiltered: true, serviceCategory: "Both" })).toBe(false);
  const write = jest.fn(async () => {});
  mockApiGet.mockResolvedValueOnce([{ id: "j1" }]);
  const ok = canWriteThroughJobs({ crewFiltered: false, serviceCategory: "Pool" });
  await cachedGet("/jobs?x&service_category=pool", { writeThrough: ok ? write : undefined });
  expect(write).not.toHaveBeenCalled();
});

it("Y6 · cache save FIRES when All is selected (normal path)", async () => {
  expect(canWriteThroughJobs({ crewFiltered: false, serviceCategory: "All" })).toBe(true);
  const write = jest.fn(async () => {});
  mockApiGet.mockResolvedValueOnce([{ id: "j1" }]);
  await cachedGet("/jobs?x", { writeThrough: canWriteThroughJobs({ crewFiltered: false, serviceCategory: "All" }) ? write : undefined });
  expect(write).toHaveBeenCalledWith([{ id: "j1" }]);
});

it("Y7 · state persisted to AsyncStorage and restored on remount; All clears the key", async () => {
  const a = renderHook(() => useScheduleServiceCategory());
  await waitFor(() => expect(a.result.current[0]).toBe("All"));
  act(() => { a.result.current[1]("Landscaping"); });
  expect(a.result.current[0]).toBe("Landscaping");
  await waitFor(() => expect(mockStore[SERVICE_CATEGORY_KEY]).toBe("Landscaping"));
  a.unmount();
  const b = renderHook(() => useScheduleServiceCategory());
  await waitFor(() => expect(b.result.current[0]).toBe("Landscaping"));
  act(() => { b.result.current[1]("All"); });
  await waitFor(() => expect(SERVICE_CATEGORY_KEY in mockStore).toBe(false));
});

it("Y8 · screen wiring lock: chips mounted for all roles above the tech filter; write-through gated; forced refetch on change; load deps include category", () => {
  const chips = SRC.indexOf("<ServiceCategoryChips value={serviceCategory} onChange={setServiceCategory} />");
  expect(chips).toBeGreaterThan(-1);
  expect(chips).toBeLessThan(SRC.indexOf('testID="schedule-tech-filter-row"'));
  expect(SRC.slice(chips - 200, chips)).not.toMatch(/!isTech &&\s*\($/); // not tech-gated
  expect(SRC).toContain("writeThrough: writeThroughOk ? async (d) => {");
  expect(SRC).toContain("const writeThroughOk = canWriteThroughJobs({ crewFiltered, serviceCategory });");
  expect(SRC).not.toContain("writeThrough: crewFiltered ? undefined");
  expect(SRC).toContain("}, [focus, user?.id, crewFilter, isTech, resolvedTechId, serviceCategory]);");
  expect(SRC).toMatch(/categoryEffectMounted\.current = true; return; }\n\s+load\(true\);\n\s+}, \[serviceCategory\]\);/);
});
