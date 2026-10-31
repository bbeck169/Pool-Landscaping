/**
 * TD-mobile-header-layout-cleanup (Schedule only) · structure lock.
 * The calendar screen (2.5k lines) has no passing render harness, so this pins the
 * header structure by source scan; true pixel truncation is verified by live
 * screenshots at 320 / 375 / 414 (see ship receipt).
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render } from "@testing-library/react-native";

jest.mock("@/src/offline", () => ({ useOnline: () => true }));
import OfflineBadge from "@/src/components/OfflineBadge";

const SRC = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf8");
const HEADER = SRC.slice(SRC.indexOf("<Header\n        title=\"Schedule\""), SRC.indexOf("{/* Sync route toast */}"));
const RIGHT = HEADER.slice(HEADER.indexOf("right={"), HEADER.indexOf("schedule-status-strip"));

it("H1 · OfflineBadge is no longer in the Header title row (right cluster)", () => {
  expect(RIGHT).not.toContain("<OfflineBadge");
  expect(RIGHT).toContain('testID="schedule-header-sync-badge"');
  expect(RIGHT).toContain('testID="schedule-header-bell"');
});

it("H2 · OfflineBadge renders in a separate strip directly under the Header", () => {
  const strip = HEADER.slice(HEADER.indexOf('testID="schedule-status-strip"'));
  expect(HEADER.indexOf("/>\n\n      {/* TD-mobile-header-layout-cleanup")).toBeGreaterThan(-1); // Header closed before the strip
  expect(strip).toMatch(/<OfflineBadge testID="schedule-header-offline-badge"/);
  expect(SRC).toMatch(/statusStrip: \{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 16, paddingTop: 6 \}/);
});

it("H2b · narrow phones (<360): header actions (Filters + ⋯, which now hold Sync-route + Refresh) move from the title row to the strip; wide keep them in the header", () => {
  expect(SRC).toContain("const compactHeader = isCompactScheduleHeader(winWidth);");
  expect(RIGHT).toContain("{!compactHeader && headerActions}"); // Schedule declutter: Filters + ⋯ replace Sync/Refresh
  const strip = HEADER.slice(HEADER.indexOf('testID="schedule-status-strip"'));
  expect(strip).toContain("{compactHeader && headerActions}");
  expect(SRC.match(/testID="schedule-sync-route"/g)).toHaveLength(1); // single definition, rendered in exactly one place
  expect(SRC.match(/testID="schedule-refresh"/g)).toHaveLength(1);
});

it("H3 · bell has no fixed 52px margin; right cluster does not shrink (title is the only ellipsizing element)", () => {
  expect(SRC).not.toContain("marginRight: 52");
  expect(RIGHT).toMatch(/flexDirection: "row", alignItems: "center", gap: 8, flexShrink: 0/);
});

it("H4 · strip collapses when there is nothing to report (OfflineBadge → null when online + synced)", () => {
  const q = render(<OfflineBadge testID="schedule-header-offline-badge" cacheStats={{ cached: 3, total: 3, lastSyncedAt: null, syncStatus: "synced" } as any} />);
  expect(q.queryByTestId("schedule-header-offline-badge")).toBeNull();
});

it("H5 · failed sync still shows the existing red 'Sync failed — retry' pill in the strip", () => {
  const q = render(<OfflineBadge testID="schedule-header-offline-badge" cacheStats={{ cached: 0, total: 3, lastSyncedAt: null, syncStatus: "failed" } as any} />);
  expect(q.getByTestId("offline-badge-label").props.children).toBe("Sync failed — retry");
});
