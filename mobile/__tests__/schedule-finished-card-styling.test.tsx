/**
 * Schedule finished-state card styling — mobile parity with web e62babc5f.
 * Finished (completed / closed / cancelled / skipped; case + whitespace
 * insensitive) → card bg #F3F4F6 + body text #374151. Everything else keeps
 * its K50 bg; `missed` stays #FCA5A5; status pills keep their own colors.
 *
 * JobRow lives inside calendar.tsx (not exported) and the full-screen
 * calendar render suites are pre-existing failures (theme `bg` undefined),
 * so the card treatment is asserted as: resolved style = what JobRow computes
 * (helper outputs) + the JobRow source wiring that consumes them.
 */
import fs from "fs";
import path from "path";
import {
  K50_JOB_STATUS_BG, jobStatusColor, isFinishedJobStatus, jobStatusTextColor,
  isCompletedCardStatus, K50_FINISHED_FG,
} from "@/src/lib/jobStatus";

const CAL = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf-8");
const JOB_ROW = CAL.slice(CAL.indexOf("function JobRow("), CAL.indexOf("/* ═══ Calendar view"));
const WEB = fs.readFileSync(path.resolve(__dirname, "../../frontend/src/lib/jobStatus.js"), "utf-8");
const SURFACE = "surface";

/** Mirrors JobRow: card bg + body text color for a status. */
const card = (status: string | null) => ({
  backgroundColor: jobStatusColor(status) || SURFACE,
  bodyColor: jobStatusTextColor(status) || "onSurface/default",
});

const lum = (hex: string) => {
  const c = hex.replace("#", "").match(/../g)!.map((h) => parseInt(h, 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const contrast = (a: string, b: string) => {
  const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m);
  return (x + 0.05) / (y + 0.05);
};

describe("finished statuses → #F3F4F6 bg + #374151 body text", () => {
  it.each(["completed", "closed", "cancelled", "skipped", "canceled", "done"])("%s", (s) => {
    expect(card(s)).toEqual({ backgroundColor: "#F3F4F6", bodyColor: "#374151" });
    expect(isFinishedJobStatus(s)).toBe(true);
  });

  it("case + whitespace insensitive (web parity)", () => {
    for (const s of ["  Completed ", "CLOSED", " Cancelled", "SKIPPED\n", "Canceled"]) {
      expect(card(s)).toEqual({ backgroundColor: "#F3F4F6", bodyColor: "#374151" });
    }
  });
});

describe("non-finished statuses keep their existing colors", () => {
  it.each([
    ["open", "#EAF7F0"], ["scheduled", "#EAF7F0"], ["pending", "#EAF7F0"],
    ["in_progress", "#FEF3C7"], ["active", "#FEF3C7"],
    ["on_my_way", SURFACE], ["on_hold", SURFACE], ["requested", SURFACE], ["reopened", SURFACE],
    ["could_not_service", SURFACE], ["missed", "#FCA5A5"],
  ])("%s → %s, default body text", (s, bg) => {
    expect(card(s).backgroundColor).toBe(bg);
    expect(card(s).backgroundColor).not.toBe("#F3F4F6");
    expect(jobStatusTextColor(s)).toBeNull();
    expect(isFinishedJobStatus(s)).toBe(false);
  });

  it("empty / null / undefined → not finished, surface fallback", () => {
    for (const s of ["", "   ", null, undefined]) {
      expect(isFinishedJobStatus(s as any)).toBe(false);
      expect(jobStatusTextColor(s as any)).toBeNull();
    }
  });
});

describe("helpers match web e62babc5f byte-for-byte", () => {
  it("K50_JOB_STATUS_BG equals the live web map", () => {
    const start = WEB.indexOf("K50_JOB_STATUS_BG = Object.freeze({");
    const block = WEB.slice(start, WEB.indexOf("});", start));
    const webMap: Record<string, string> = {};
    for (const m of block.matchAll(/^\s*([a-z_]+):\s*"(#[0-9A-Fa-f]{6})"/gm)) webMap[m[1]] = m[2];
    expect({ ...K50_JOB_STATUS_BG }).toEqual(webMap);
  });

  it("isFinishedJobStatus / jobStatusTextColor: same names, alias table, return values", () => {
    expect(WEB).toContain("export function isFinishedJobStatus(status)");
    expect(WEB).toContain('return isFinishedJobStatus(status) ? "#374151" : null;');
    expect(K50_FINISHED_FG).toBe("#374151");
    for (const k of ['closed: "completed"', 'done: "completed"', 'canceled: "cancelled"']) expect(WEB).toContain(k);
  });
});

describe("JobRow wiring", () => {
  it("card bg from the K50 map (border/shadow/layout untouched)", () => {
    expect(JOB_ROW).toContain("const k50CardBg = k50JobStatusColor(job.status) || colors.surface;");
    expect(JOB_ROW).toContain("borderLeftWidth: 4, borderLeftColor: statusBorder, backgroundColor: k50CardBg");
  });

  it("body text (service tag, customer name, address, BH meta, icons) uses jobStatusTextColor", () => {
    expect(JOB_ROW).toContain("const finishedFg = jobStatusTextColor(job.status);");
    expect(JOB_ROW).toContain("const fg = finishedFg ? { color: finishedFg } : null;");
    expect(JOB_ROW).toMatch(/gStyles\.svcTag, \{ color: svc\.tag \}, fg\]/);
    expect(JOB_ROW).toContain("gStyles.cust, { flexShrink: 1 }, fg]} numberOfLines={1} testID={`job-card-cust-${job.id}`}");
    expect(JOB_ROW).toContain("finishedFg ? { ...gStyles.addr, color: finishedFg } : gStyles.addr");
    expect(JOB_ROW).toMatch(/gStyles\.metaText, fg\]/);
    expect(JOB_ROW).not.toContain("K50_COMPLETED_MUTED_FG");
  });

  it("status pills keep their colored chips on finished cards (not blanket-grey'd)", () => {
    expect(JOB_ROW).toContain("<View style={[gStyles.statusPill, { backgroundColor: pill.bg }]}>");
    expect(JOB_ROW).toContain("<Text style={[gStyles.statusText, { color: pill.fg }]}>{pill.label}</Text>");
    expect(CAL).toContain('completed:  { bg: "#DCFCE7", fg: "#166534", label: "Closed" },');
    expect(CAL).toContain('cancelled:  { bg: "#F3F4F6", fg: "#4B5563", label: "Cancelled" },');
    expect(CAL).toContain('skipped:    { bg: "#E5E7EB", fg: "#374151", label: "Skipped" },');
  });

  it("✓ icon stays completed-only — cancelled/skipped share the bg but not the check", () => {
    expect(JOB_ROW).toContain("const done = isCompletedCardStatus(job.status);");
    for (const s of ["completed", "closed", "done", " COMPLETED "]) expect(isCompletedCardStatus(s)).toBe(true);
    for (const s of ["cancelled", "canceled", "skipped", "missed", "open"]) expect(isCompletedCardStatus(s)).toBe(false);
  });
});

describe("WCAG", () => {
  it("#374151 on #F3F4F6 is AAA (≥ 7:1; actual 9.37:1)", () => {
    const r = contrast(K50_FINISHED_FG, K50_JOB_STATUS_BG.completed);
    expect(r).toBeGreaterThanOrEqual(7);
    expect(r).toBeCloseTo(9.37, 1);
  });
});
