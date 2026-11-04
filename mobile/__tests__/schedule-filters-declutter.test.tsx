/**
 * Schedule filters — source locks for calendar.tsx (no screen render harness:
 * k32 / schedule-map-toggle baseline).
 *
 * R1–R3 · TD-mobile-schedule-service-category-filter-remove (web 5b97b57b3):
 *   M3a's Pool / Landscaping / Both / All chip-group, its lib
 *   (scheduleServiceCategory) + hook (useScheduleServiceCategory) are gone;
 *   /jobs no longer carries `service_category` (BE still accepts it).
 *   Preserved from the old m3a suite: the crew-filter offline write-through
 *   skip (ex-Y5/Y6) + the Schedule declutter D1–D5 locks below.
 */
import fs from "fs";
import path from "path";

import { cachedGet } from "@/src/lib/offline/apiCache";

const mockApiGet = jest.fn();
jest.mock("@/src/api", () => {
  class ApiNetworkError extends Error {}
  return { api: { get: (...a: any[]) => mockApiGet(...a) }, ApiNetworkError };
});

const ROOT = path.resolve(__dirname, "..");
const SRC = fs.readFileSync(path.join(ROOT, "app/(app)/schedule/calendar.tsx"), "utf8");
beforeEach(() => { mockApiGet.mockReset(); });

it("R1 · chip-group, lib and hook are deleted; calendar has no category state / mount / refetch effect", () => {
  for (const f of [
    "src/components/schedule/ServiceCategoryChips.tsx",
    "src/lib/scheduleServiceCategory.ts",
    "src/hooks/useScheduleServiceCategory.ts",
  ]) expect(fs.existsSync(path.join(ROOT, f))).toBe(false);
  expect(SRC).not.toMatch(/ServiceCategoryChips|useScheduleServiceCategory|scheduleServiceCategory|serviceCategoryParam|canWriteThroughJobs/);
  expect(SRC).not.toMatch(/serviceCategory|categoryEffectMounted/);
  expect(SRC).not.toMatch(/testID=\{?["`]schedule-service-category/);
  expect(SRC).toContain("TD-mobile-schedule-service-category-filter-remove");
});

it("R2 · /jobs + month scope carry crew / tech only — no service_category", () => {
  expect(SRC).toContain("const jobsUrl = `/jobs?start=${start}&end=${end}${!isTech && crewFiltered ? `&crew_id=${crewFilter}` : \"\"}${techScope}`;");
  expect(SRC).toContain("const monthScopeQuery = `${!isTech && crewFilter ? `&crew_id=${crewFilter}` : \"\"}${isTech && resolvedTechId ? `&technician_id=${resolvedTechId}` : \"\"}`;");
  // No query-string injection left (breadcrumb comments may still name the BE param).
  expect(SRC).not.toMatch(/&service_category=/);
  expect(SRC).toContain("}, [focus, user?.id, crewFilter, isTech, resolvedTechId]);");
  // Evaluate the jobsUrl template: crew active, admin.
  const start = "2026-10-19", end = "2026-11-09", isTech = false, crewFiltered = true, crewFilter = "c1", techScope = "";
  const url = `/jobs?start=${start}&end=${end}${!isTech && crewFiltered ? `&crew_id=${crewFilter}` : ""}${techScope}`;
  expect(url).toBe("/jobs?start=2026-10-19&end=2026-11-09&crew_id=c1");
});

it("R3 · (ex-Y5/Y6) offline write-through still skipped for a crew-filtered subset, fires otherwise", async () => {
  expect(SRC).toContain("const writeThroughOk = !crewFiltered;");
  expect(SRC).toContain("writeThrough: writeThroughOk ? async (d) => {");
  expect(SRC).not.toContain("writeThrough: crewFiltered ? undefined");
  const run = async (crewFiltered: boolean) => {
    const write = jest.fn(async () => {});
    mockApiGet.mockResolvedValueOnce([{ id: "j1" }]);
    const writeThroughOk = !crewFiltered;
    await cachedGet("/jobs?x", { writeThrough: writeThroughOk ? write : undefined });
    return write;
  };
  expect(await run(true)).not.toHaveBeenCalled();
  expect(await run(false)).toHaveBeenCalledWith([{ id: "j1" }]);
});

describe("Schedule declutter · overflow actions + Filters drawer (source locks)", () => {
  const fs = require("fs");
  const path = require("path");
  const S = fs.readFileSync(path.join(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf8");
  const HEADER = S.slice(S.indexOf("<Header\n        title=\"Schedule\""), S.indexOf('testID="schedule-root-scroll"'));
  const sheet = (id: string) => S.slice(S.indexOf(`testID="${id}">`), S.indexOf("</SwipeSheet>", S.indexOf(`testID="${id}">`)));

  it("D1 · top bar: Sync Route + Refresh icons gone; Filters + ⋯ (labelled, expanded state) via headerActions", () => {
    expect(HEADER).not.toMatch(/testID="schedule-sync-route"|testID="schedule-refresh"/);
    expect(HEADER).toContain("{!compactHeader && headerActions}");
    expect(S).toMatch(/onPress=\{\(\) => setFiltersOpen\(true\)\}[\s\S]{0,200}testID="schedule-filters-button"[\s\S]{0,80}accessibilityLabel="Open filters"[\s\S]{0,120}accessibilityState=\{\{ expanded: filtersOpen \}\}/);
    expect(S).toMatch(/onPress=\{\(\) => setActionsSheetOpen\(true\)\}[\s\S]{0,120}testID="schedule-actions-overflow"[\s\S]{0,80}accessibilityLabel="Open actions"/);
  });

  it("D2 · actions sheet holds the SAME Sync Route + Refresh controls (handlers, offline-disable, spinners)", () => {
    const a = sheet("schedule-actions-sheet");
    expect(a).toContain("{routeActions}");
    expect(S).toMatch(/onPress=\{handleSyncRoute\}\s*disabled=\{syncingRoute \|\| hydrationMeta\?\.inProgress \|\| !online\}[\s\S]{0,200}testID="schedule-sync-route"/);
    expect(S).toContain('testID="schedule-sync-route-progress"');
    expect(S).toContain("onPress={() => { if (!refreshing) { setRefreshing(true); load(true).finally(() => setRefreshing(false)); } }}");
    expect(S).toMatch(/disabled=\{refreshing\}[\s\S]{0,120}testID="schedule-refresh"/);
    expect(S).toContain('testID="schedule-refresh-spinner"');
  });

  it("D3 · Filters drawer: admin-only inline tech list (same handler, no nested modal) + cancelled toggle", () => {
    const f = sheet("schedule-filters-sheet");
    expect(f).toMatch(/\{!isTech && \(\s*<View style=\{styles\.filtersSection\} testID="schedule-tech-filter-row">/);
    expect(f).toContain('onPress={() => { handleTechFilterChange("all"); }}');
    expect(f).toContain("onPress={() => { handleTechFilterChange(t.id); }}");
    expect(f).toMatch(/onPress=\{toggleShowCancelled\}[\s\S]{0,80}testID="schedule-show-cancelled-toggle"/);
    expect(S).not.toMatch(/techPickerOpen|setTechPickerOpen/);
    // the cancelled toggle + tech row no longer render in the page body
    expect(S.indexOf('testID="schedule-show-cancelled-toggle"')).toBeGreaterThan(S.indexOf('testID="schedule-filters-sheet"'));
  });

  it("D4 · Filters badge: admin = tech selected OR cancelled shown; tech = cancelled shown only", () => {
    expect(S).toContain('const filtersActive = isTech ? showCancelled : (techFilter !== "all" || showCancelled);');
    expect(S).toContain('{filtersActive ? <View style={styles.filtersDot} testID="schedule-filters-active-badge" /> : null}');
  });

  it("D5 · regression lock: mode toggle, Actions, Add Job, bell, SyncBadge untouched", () => {
    expect(S).toContain('{(["calendar", "grid", "month"] as const).map((m) => {');
    expect(S).toContain('testID="schedule-mode-switch"');
    expect(S).toContain('testID="grid-actions-trigger"');
    expect(S).toContain('testID="mobile-schedule-add-job-btn-grid"');
    expect(S).toContain('testID="mobile-schedule-add-job-btn-calendar"');
    expect(HEADER).toMatch(/<SyncBadge testID="schedule-header-sync-badge" \/>\s*\{isTech \? \(\s*<View testID="schedule-header-bell">/);
  });
});
