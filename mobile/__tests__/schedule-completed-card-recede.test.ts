/**
 * Oct-2026 mobile hotfix — completed/closed Schedule job cards RECEDE.
 *
 * Was: bold coral-red #ff4542 bg + #ff4542 left border + white text.
 * Was (Oct-2026 soft green): emerald-50 #ECFDF5 bg; now finished gray #F3F4F6 (web e62babc5f), emerald-300 #6EE7B7 border, ✓
 * (Ionicons checkmark-circle, 18px, dark green #065F46) top-right next to
 * the "Closed" pill, standard primary text, AA-safe #52525B secondary.
 * (lucide-react-native is NOT installed → Ionicons, no new dep.)
 *
 *  1. Every NON-completed status renders exactly as before (bg + border)
 *  2. Status → treatment table snapshot
 *  3. WCAG AA (≥ 4.5:1) for every text colour on the completed bg
 *  4. JobRow wiring: ✓ only when done, a11y label "Completed",
 *     cancelled styling untouched
 */
import * as fs from "fs";
import * as path from "path";
import { jobStatusColor, isCompletedCardStatus, K50_COMPLETED_BG, K50_COMPLETED_MUTED_FG, K50_COMPLETED_ACCENT } from "@/src/lib/jobStatus";
import { getStatusBorderColor } from "@/src/utils/scheduleStatus";

const CAL = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf-8");
const JOB_ROW = CAL.slice(CAL.indexOf("function JobRow("), CAL.indexOf("/* ═══ Calendar view"));

const STATUSES = [
  "open", "scheduled", "pending", "in_progress", "active", "completed", "closed", "done", "COMPLETED",
  "cancelled", "canceled", "skipped", "on_hold", "requested", "reopened", "could_not_service", "", null,
];
const treatment = (s: string | null) => ({
  bg: jobStatusColor(s) ?? "surface",
  border: getStatusBorderColor(s),
  completed: isCompletedCardStatus(s),
});

// Pre-hotfix values (HEAD before this change) for every non-completed status.
const BEFORE_NON_COMPLETED: Record<string, { bg: string; border: string }> = {
  open: { bg: "#EAF7F0", border: "#2563EB" },
  scheduled: { bg: "#EAF7F0", border: "#2563EB" },
  pending: { bg: "#EAF7F0", border: "#2563EB" },
  in_progress: { bg: "#FEF3C7", border: "#2563EB" },
  active: { bg: "#FEF3C7", border: "#2563EB" },
  // Feb-2026 finished-state styling (web e62babc5f): cancelled/skipped → gray-100.
  cancelled: { bg: "#F3F4F6", border: "#2563EB" },
  canceled: { bg: "#F3F4F6", border: "#2563EB" },
  skipped: { bg: "#F3F4F6", border: "#2563EB" },
  on_hold: { bg: "surface", border: "#2563EB" },
  requested: { bg: "surface", border: "#2563EB" },
  reopened: { bg: "surface", border: "#2563EB" },
  could_not_service: { bg: "surface", border: "#2563EB" },
  "": { bg: "surface", border: "#2563EB" },
};

describe("completed card recede · status scope", () => {
  it("non-completed statuses are byte-identical to pre-hotfix", () => {
    for (const [s, before] of Object.entries(BEFORE_NON_COMPLETED)) {
      const t = treatment(s);
      expect({ s, bg: t.bg, border: t.border }).toEqual({ s, ...before });
      expect(t.completed).toBe(false);
    }
    expect(treatment(null)).toEqual({ bg: "surface", border: "#2563EB", completed: false });
  });

  it("completed bg no longer red; completed/closed/done all recede", () => {
    for (const s of ["completed", "closed", "done", "COMPLETED"]) {
      expect(jobStatusColor(s)).toBe("#F3F4F6");
      expect(isCompletedCardStatus(s)).toBe(true);
    }
    for (const s of ["completed", "closed", "done", "COMPLETED"]) expect(getStatusBorderColor(s)).toBe("#6EE7B7");
    expect(JSON.stringify(STATUSES.map(treatment)).toLowerCase()).not.toContain("#ff4542");
  });

  it("status → treatment table (snapshot)", () => {
    expect(Object.fromEntries(STATUSES.map((s) => [String(s), treatment(s)]))).toMatchSnapshot();
  });
});

/* ── WCAG 2.x relative-luminance contrast ──────────────────────── */
const lum = (hex: string) => {
  const c = hex.replace("#", "").match(/../g)!.map((h) => parseInt(h, 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const contrast = (a: string, b: string) => {
  const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m);
  return (x + 0.05) / (y + 0.05);
};

describe("completed card recede · WCAG AA legibility", () => {
  it("finished body #374151 is AAA (9.37:1); #09090B, #52525B, ✓ #065F46 all ≥ 4.5:1 on #F3F4F6", () => {
    expect(contrast("#374151", K50_COMPLETED_BG)).toBeGreaterThanOrEqual(7);
    expect(contrast("#09090B", K50_COMPLETED_BG)).toBeGreaterThan(17);
    expect(contrast(K50_COMPLETED_MUTED_FG, K50_COMPLETED_BG)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(K50_COMPLETED_ACCENT, K50_COMPLETED_BG)).toBeGreaterThanOrEqual(4.5);
  });

  it("service-tag hues would FAIL AA on the finished bg (why the tag text is overridden)", () => {
    for (const tag of ["#059669", "#0891B2"]) expect(contrast(tag, K50_COMPLETED_BG)).toBeLessThan(4.5);
    expect(contrast(K50_COMPLETED_ACCENT, "#ECFDF5")).toBeGreaterThan(7);
  });

  it("'Closed' pill (#166534 on #DCFCE7) stays AA", () => {
    expect(contrast("#166534", "#DCFCE7")).toBeGreaterThanOrEqual(4.5);
  });
});

describe("completed card recede · JobRow wiring", () => {
  it("✓ checkmark-circle 18px dark green, top-right row beside the status pill, only when done", () => {
    const i = JOB_ROW.indexOf("<View style={gStyles.cardRightTop}>");
    expect(i).toBeGreaterThan(-1);
    const block = JOB_ROW.slice(i, JOB_ROW.indexOf("{pill.label}", i));
    expect(block).toMatch(/\{done \? \(/);
    expect(block).toContain('testID={`job-card-done-check-${job.id}`}');
    expect(block).toContain('accessibilityLabel="Completed"');
    expect(block).toContain('<Ionicons name="checkmark-circle" size={18} color={K50_COMPLETED_ACCENT} />');
    expect(block.indexOf("checkmark-circle")).toBeLessThan(block.indexOf("gStyles.statusPill"));
    expect(CAL).toContain('cardRightTop: { flexDirection: "row", alignItems: "center", gap: 4 },');
  });

  it("address uses finished #374151 (jobStatusTextColor) on finished cards; card bg/border wiring unchanged", () => {
    expect(JOB_ROW).toContain("finishedFg ? { ...gStyles.addr, color: finishedFg } : gStyles.addr");
    expect(JOB_ROW).toContain("borderLeftColor: statusBorder, backgroundColor: k50CardBg");
  });

  it("cancelled → finished gray #F3F4F6 bg (web e62babc5f), gray 'Cancelled' pill unchanged", () => {
    expect(jobStatusColor("cancelled")).toBe("#F3F4F6");
    expect(CAL).toContain('cancelled:  { bg: "#F3F4F6", fg: "#4B5563", label: "Cancelled" },');
  });
});
