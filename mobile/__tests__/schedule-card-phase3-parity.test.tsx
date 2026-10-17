/**
 * Phase 3 / 3b mobile parity — schedule job card:
 *  F1 NoteBlock + Customer/Pool/Landscape inline notes
 *  F2 completed card — finished gray #F3F4F6 (web e62babc5f; was Oct-2026 soft green #ECFDF5
 *     bg, #6EE7B7 border, ✓ #065F46, AA-safe #52525B secondary); was bold red
 *     #ff4542 + white fg (web 85fd76f17, web unchanged)
 *  F3 orange Navigate button (order, encoding, disabled, deep-link fallback)
 */
import * as fs from "fs";
import * as path from "path";
import React from "react";
import { Linking, Platform } from "react-native";
import { render, fireEvent } from "@testing-library/react-native";
import NoteBlock from "@/src/components/schedule/NoteBlock";
import JobNotesCallout from "@/src/components/schedule/JobNotesCallout";
import NavigateMapsButton, { resolveNavigateAddress, nativeNavUrl, webDirectionsUrl, openNavigation } from "@/src/components/schedule/NavigateMapsButton";
import {
  jobStatusColor, isCompletedCardStatus, K50_COMPLETED_BG, K50_COMPLETED_MUTED_FG, K50_COMPLETED_ACCENT, K50_JOB_STATUS_BG,
} from "@/src/lib/jobStatus";
import { getStatusBorderColor } from "@/src/utils/scheduleStatus";

const CAL = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf-8");
const JOB_ROW = CAL.slice(CAL.indexOf("function JobRow("), CAL.indexOf("/* ═══ Calendar view"));

describe("F1 · NoteBlock", () => {
  it("hides on null / empty / whitespace", () => {
    for (const t of [null, "", "   \n "]) expect(render(<NoteBlock label="Pool note" text={t} testID="nb" />).toJSON()).toBeNull();
  });
  it("short note: label prefix, 3-line clamp, no toggle", () => {
    const r = render(<NoteBlock label="Pool note" text="Check impeller" testID="nb" />);
    expect(r.getByTestId("nb-text").props.numberOfLines).toBe(3);
    expect(r.getByText("Pool note: ")).toBeTruthy();
    expect(r.queryByTestId("nb-toggle")).toBeNull();
  });
  it(">120 chars or newline → Show more toggles the clamp", () => {
    const r = render(<NoteBlock label="Pool note" text={"x".repeat(121)} testID="nb" />);
    fireEvent.press(r.getByTestId("nb-toggle"));
    expect(r.getByTestId("nb-text").props.numberOfLines).toBeUndefined();
    expect(r.getByText("Show less")).toBeTruthy();
    expect(render(<NoteBlock label="L" text={"a\nb"} testID="n2" />).getByTestId("n2-toggle")).toBeTruthy();
    expect(render(<NoteBlock label="L" text={"x".repeat(120)} testID="n3" />).queryByTestId("n3-toggle")).toBeNull();
  });
  it("callout renders Customer → Pool → Landscape with independent toggles; pool-only still renders", () => {
    const long = "y".repeat(150);
    const r = render(<JobNotesCallout jobId="j" customerNote="Gate open" poolNote={long} landscapeNote={long} />);
    const ids = r.UNSAFE_root.findAll((n: any) => /^job-notes-(preview|pool|landscape)-j$/.test(n.props.testID || "")).map((n: any) => n.props.testID);
    expect([...new Set(ids)]).toEqual(["job-notes-preview-j", "job-notes-pool-j", "job-notes-landscape-j"]);
    fireEvent.press(r.getByTestId("job-notes-pool-j-toggle"));
    expect(r.getByTestId("job-notes-pool-j-text").props.numberOfLines).toBeUndefined();
    expect(r.getByTestId("job-notes-landscape-j-text").props.numberOfLines).toBe(3);
    expect(render(<JobNotesCallout jobId="k" poolNote="Only pool" />).getByTestId("job-notes-pool-k")).toBeTruthy();
    expect(render(<JobNotesCallout jobId="z" poolNote=" " landscapeNote={null} />).toJSON()).toBeNull();
  });
  it("calendar card wires service_notes_pool / service_notes_landscape", () => {
    expect(JOB_ROW).toMatch(/poolNote=\{job\.service_notes_pool\}\s+landscapeNote=\{job\.service_notes_landscape\}/);
  });
});

describe("F2 · completed card (finished-state gray — web e62babc5f parity)", () => {
  it("completed (+aliases) → #F3F4F6; ✓ only for completed/closed/done", () => {
    expect(jobStatusColor("completed")).toBe("#F3F4F6");
    expect(isCompletedCardStatus("completed")).toBe(true);
    expect(isCompletedCardStatus("closed")).toBe(true);
    expect(isCompletedCardStatus("done")).toBe(true);
    for (const s of ["scheduled", "open", "in_progress", "cancelled", "skipped", "on_hold", "", null]) {
      expect(isCompletedCardStatus(s as any)).toBe(false);
    }
    expect([jobStatusColor("scheduled"), jobStatusColor("in_progress"), jobStatusColor("cancelled"), jobStatusColor("skipped")])
      .toEqual(["#EAF7F0", "#FEF3C7", "#F3F4F6", "#F3F4F6"]);
  });
  it("completed treatment tokens derive from the map", () => {
    expect(K50_COMPLETED_BG).toBe(K50_JOB_STATUS_BG.completed);
    expect([K50_COMPLETED_BG, K50_COMPLETED_MUTED_FG, K50_COMPLETED_ACCENT]).toEqual(["#F3F4F6", "#52525B", "#065F46"]);
  });
  it("left-border color: completed/closed/done → soft green #6EE7B7, everything else blue", () => {
    for (const st of ["completed", "COMPLETED", "closed", "done"]) expect(getStatusBorderColor(st)).toBe("#6EE7B7");
    expect([getStatusBorderColor("scheduled"), getStatusBorderColor("cancelled"), getStatusBorderColor(null)])
      .toEqual(["#2563EB", "#2563EB", "#2563EB"]);
  });
  it("'Closed' status pill stays green (complementary signal, web parity)", () => {
    expect(CAL).toContain('completed:  { bg: "#DCFCE7", fg: "#166534", label: "Closed" },');
  });
  it("JobRow: body text → #374151 on finished cards (incl. customer name); ✓ stays completed-only; no white flip", () => {
    expect(JOB_ROW).toContain("const done = isCompletedCardStatus(job.status);");
    expect(JOB_ROW).toContain("const finishedFg = jobStatusTextColor(job.status);");
    expect(JOB_ROW).toContain("const fg = finishedFg ? { color: finishedFg } : null;");
    for (const re of [/gStyles\.svcTag, \{ color: svc\.tag \}, fg\]/, /gStyles\.metaText, fg\]/, /reader-outline" size=\{12\} color=\{finishedFg \|\|/, /chevron-forward" size=\{20\} color=\{finishedFg \|\|/])
      expect(JOB_ROW).toMatch(re);
    expect(JOB_ROW).toMatch(/gStyles\.cust, \{ flexShrink: 1 \}, fg\]/);
    expect(JOB_ROW).not.toMatch(/onRed|K50_ON_BOLD_RED_FG|isBoldRedStatus|#FFFFFF/);
  });
});

describe("F3 · Navigate button", () => {
  afterEach(() => jest.restoreAllMocks());
  it("is last in the action row: OMW → CNS → Navigate", () => {
    const a = JOB_ROW.indexOf("<OnMyWayButton"), b = JOB_ROW.indexOf("<CouldNotServiceButton"), c = JOB_ROW.indexOf("<NavigateMapsButton");
    expect(a).toBeGreaterThan(-1);
    expect(a < b && b < c).toBe(true);
  });
  it("address priority service_address → address → disabled", () => {
    expect(resolveNavigateAddress({ service_address: " 1 Pool Ln ", address: "2 Home" })).toBe("1 Pool Ln");
    expect(resolveNavigateAddress({ service_address: "  ", address: "2 Home" })).toBe("2 Home");
    expect(resolveNavigateAddress({})).toBe("");
    const r = render(<NavigateMapsButton job={{ id: "j" }} />);
    expect(r.getByTestId("schedule-card-navigate-j").props.accessibilityState.disabled).toBe(true);
  });
  it("encodes the address in both URLs", () => {
    expect(nativeNavUrl("12 Main St #4, Peoria AZ")).toBe("google.navigation:q=12%20Main%20St%20%234%2C%20Peoria%20AZ");
    expect(webDirectionsUrl("A&B")).toBe("https://www.google.com/maps/dir/?api=1&destination=A%26B");
  });
  it("Android: native deep link; falls back to web URL when it throws", async () => {
    Platform.OS = "android";
    const open = jest.spyOn(Linking, "openURL").mockResolvedValue(true as any);
    expect(await openNavigation("1 Pool Ln")).toBe("native");
    expect(open).toHaveBeenLastCalledWith("google.navigation:q=1%20Pool%20Ln");
    open.mockRejectedValueOnce(new Error("no activity"));
    expect(await openNavigation("1 Pool Ln")).toBe("web");
    expect(open).toHaveBeenLastCalledWith("https://www.google.com/maps/dir/?api=1&destination=1%20Pool%20Ln");
  });
  it("iOS without the native scheme → web URL; press wires through", async () => {
    Platform.OS = "ios";
    jest.spyOn(Linking, "canOpenURL").mockResolvedValue(false);
    const open = jest.spyOn(Linking, "openURL").mockResolvedValue(true as any);
    const r = render(<NavigateMapsButton job={{ id: "j", address: "9 Elm" }} />);
    fireEvent.press(r.getByTestId("schedule-card-navigate-j"));
    await new Promise((res) => setImmediate(res));
    expect(open).toHaveBeenCalledWith("https://www.google.com/maps/dir/?api=1&destination=9%20Elm");
  });
});
