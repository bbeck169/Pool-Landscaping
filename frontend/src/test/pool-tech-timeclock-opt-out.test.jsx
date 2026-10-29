// Ticket · Feb-2026 — Pool-tech time-clock opt-out (web).
//
// Operator-locked contract: pool technicians must NOT be
// required to clock in and must NOT see the time-clock UI at
// all. ``shouldShowTimeClock(user)`` is the shared landscape-
// vs-pool predicate used by every gate added in this ticket.
//
// This suite locks the 5 FE gates via source inspection
// (same pattern as the Item #6 Sent-column + Ticket 1
// read-only-checklist suites):
//
//   S8   TodaySchedule header "Clocked in" + "Hours logged"
//        chips → hidden for pool techs.
//   S9   ScheduleCardList "▶ Clock In & Start Report" CTA →
//        onClockIn prop undefined for pool techs ⇒ CTA block
//        does not render.
//   S10  Auto-GPS watcher useEffect → short-circuits BEFORE
//        registering watchPosition for pool techs.
//   S11  Auto-clockin toast → defensive render-gate so even
//        a stale ``autoToast`` state can't surface for pool.
//   SR   ServiceReport submit → skips the /workforce/clock-out
//        POST entirely (clean skip, not swallow-403).
//
// Source-inspection style is deliberate — the full
// TodaySchedule + ServiceReport render trees depend on dozens
// of API mocks + context providers which are locked separately
// by the K31 / K40 / phase 7C suites. We just lock the wiring
// contract.

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(__dirname, "../../..");
const R = (rel) => readFileSync(resolve(ROOT, rel), "utf8");


describe("Pool-tech opt-out · shared predicate reused", () => {
  it("timeClockVisibility helper exports shouldShowTimeClock + LANDSCAPE_DEPTS", () => {
    const src = R("frontend/src/lib/timeClockVisibility.js");
    expect(src).toContain("export function shouldShowTimeClock(user)");
    expect(src).toContain("LANDSCAPE_DEPTS");
    // BE-authoritative boolean wins over department.
    expect(src).toMatch(/user\.show_time_clock/);
  });
});


describe("Pool-tech opt-out · TodaySchedule.jsx gates", () => {
  const SRC = R("frontend/src/pages/schedule/TodaySchedule.jsx");

  it("imports the shared predicate", () => {
    expect(SRC).toMatch(
      /import\s+{\s*shouldShowTimeClock\s*}\s*from\s*"@\/lib\/timeClockVisibility"/,
    );
  });

  it("computes _tcVisible once at the top of the component", () => {
    expect(SRC).toContain("const _tcVisible = shouldShowTimeClock(user)");
  });

  // ── S8 ────────────────────────────────────────────────────────
  it("S8 — Clocked-in + Hours-logged chips gate on _tcVisible", () => {
    // Both chips must sit INSIDE a ``{_tcVisible && (<Stat ... />)}``
    // conditional.  Scan for the exact pattern on each chip's line.
    expect(SRC).toMatch(/_tcVisible\s*&&\s*\(\s*<Stat\s+label="Clocked in"/);
    expect(SRC).toMatch(/_tcVisible\s*&&\s*\(\s*<Stat\s+label="Hours logged"/);
    // The Scheduled + Miles chips still render UNCONDITIONALLY.
    const scheduledIdx = SRC.indexOf('label="Scheduled"');
    expect(scheduledIdx).toBeGreaterThan(-1);
    const scheduledLine = SRC.slice(
      SRC.lastIndexOf("\n", scheduledIdx),
      SRC.indexOf("\n", scheduledIdx),
    );
    expect(scheduledLine).not.toMatch(/_tcVisible\s*&&/);
  });

  // ── S9 ────────────────────────────────────────────────────────
  it("S9 — onClockIn prop is undefined for pool techs", () => {
    // Parent short-circuits via ``!_tcVisible ? undefined : async (job) => {…}``.
    expect(SRC).toMatch(
      /onClockIn=\{!_tcVisible\s*\?\s*undefined\s*:\s*async\s*\(job\)/,
    );
  });

  it("S9 — ScheduleCardList CTA wraps the <button> in {onClockIn && (…)}", () => {
    // The ``▶ Clock In & Start Report`` button block must sit
    // inside a truthy-``onClockIn`` conditional so an undefined
    // prop hides the whole CTA (not just no-ops the handler).
    const sliced = SRC.split("▶ Clock In & Start Report")[0];
    // The 500 chars BEFORE the label text must contain the
    // conditional wrapper opening — the real wrap sits above the
    // comment block + <button> opening tag.
    const window = sliced.slice(-500);
    expect(window).toMatch(/\{onClockIn\s*&&\s*\(/);
    expect(window).toContain("schedule-card-clockin-");
  });

  // ── S10 ───────────────────────────────────────────────────────
  it("S10 — auto-GPS useEffect short-circuits BEFORE watchPosition", () => {
    const sliced = SRC.split("Phase 19 · Auto-clock-in via GPS")[1]
      .split("useEffect(() => {")[1]
      .split("navigator.geolocation.watchPosition")[0];
    // The pool-tech guard runs after ``isTech`` / geolocation
    // feature-check but BEFORE any watcher setup.
    expect(sliced).toContain("if (!isTech || !navigator.geolocation) return;");
    expect(sliced).toContain("if (!_tcVisible) return;");
    // ``_tcVisible`` guard comes BEFORE the watcher registration.
    const tcIdx = sliced.indexOf("if (!_tcVisible) return;");
    expect(tcIdx).toBeGreaterThan(-1);
  });

  it("S10 — useEffect dependency array includes _tcVisible", () => {
    expect(SRC).toMatch(/\}, \[isTech, _tcVisible\]\);/);
  });

  // ── S11 ───────────────────────────────────────────────────────
  it("S11 — auto-toast render guards on _tcVisible", () => {
    expect(SRC).toMatch(
      /\{_tcVisible\s*&&\s*autoToast\s*&&\s*\(/,
    );
  });
});


describe("Pool-tech opt-out · ServiceReport.jsx clock-out skip", () => {
  const SRC = R("frontend/src/pages/tech/ServiceReport.jsx");

  it("imports the shared predicate + useAuth", () => {
    expect(SRC).toMatch(
      /import\s+{\s*useAuth\s*}\s*from\s*"@\/auth"/,
    );
    expect(SRC).toMatch(
      /import\s+{\s*shouldShowTimeClock\s*}\s*from\s*"@\/lib\/timeClockVisibility"/,
    );
  });

  it("computes _tcVisible once at the top of the component", () => {
    expect(SRC).toContain("const _tcVisible = shouldShowTimeClock(user)");
  });

  it("SR — /workforce/clock-out POST is gated on _tcVisible", () => {
    // The ``api.post("/workforce/clock-out", {})`` call must sit
    // inside an ``if (_tcVisible)`` block — clean skip for pool
    // techs, not a swallow-403 pattern.
    const sliced = SRC.split('api.post("/workforce/clock-out"')[0].slice(-240);
    expect(sliced).toMatch(/if\s*\(_tcVisible\)\s*\{/);
    expect(sliced).toContain("try {");
  });
});


describe("Pool-tech opt-out · defense-in-depth sanity", () => {
  it("other time-clock mount sites still gate on the shared predicate", () => {
    // These were already in place pre-ticket (TD-64 lineage); we
    // just regression-lock them here so a refactor can't
    // accidentally remove the pool-tech hide path.
    const widget = R("frontend/src/components/LandscapingClockWidget.jsx");
    expect(widget).toContain("shouldShowTimeClock");

    const nav = R("frontend/src/layouts/AppLayout.jsx");
    expect(nav).toContain("shouldShowTimeClock(user)");

    const toolsHub = R("frontend/src/pages/tech/ToolsHub.jsx");
    expect(toolsHub).toContain("shouldShowTimeClock(user)");

    const techPages = R("frontend/src/pages/tech/TechPages.jsx");
    expect(techPages).toContain("shouldShowTimeClock(user)");
  });
});
