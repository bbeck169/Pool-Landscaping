/**
 * CREW-SCHEDULE-FANOUT · Feb-2026 — ``_crew_role`` badge on the
 * tech schedule card.
 *
 * Locks the three-way render contract on ``TodaySchedule``:
 *   1.  The badge is rendered only when the backend tagged a
 *       truthy ``_crew_role`` AND the job carries a ``crew_id``
 *       — admins/dispatchers see ``_crew_role=null`` and MUST get
 *       no chip; non-crew direct-assigned jobs also skip the chip.
 *   2.  "Crew lead" copy is wired to ``_crew_role === "direct"``.
 *   3.  "Crew member" copy is wired to ``_crew_role === "member"``.
 *   4.  ``data-testid="schedule-card-crew-badge-<jid>"`` + a
 *       ``data-crew-role`` attribute carry the role for e2e selectors.
 *   5.  The ``Users`` icon from ``lucide-react`` is imported and
 *       referenced inside the chip.
 *
 * Harness mirrors ``schedule-card-directions.test.jsx`` — pure
 * source inspection on ``TodaySchedule.jsx`` so the test is
 * jsdom-free and fast. The backend contract (what ``_crew_role``
 * actually resolves to) is locked in
 * ``backend/tests/test_crew_schedule_visibility.py``.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const TODAY_SRC = readFileSync(
  resolve(__dirname, "../pages/schedule/TodaySchedule.jsx"), "utf8",
);


// Strip comments so narrative mentions of ``_crew_role`` in docstrings
// don't trip up the JSX-shape guards below.
function _stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/[^\n]*/g, "");
}
const CODE = _stripComments(TODAY_SRC);


describe("CREW-SCHEDULE-FANOUT · schedule card crew badge", () => {
  it("imports Users icon from lucide-react", () => {
    expect(TODAY_SRC).toMatch(
      /import\s*\{[^}]*\bUsers\b[^}]*\}\s*from\s*["']lucide-react["']/,
    );
  });

  it("renders the crew-badge chip gated on crew_id + _crew_role in {direct, member}", () => {
    // The JSX gate must inspect BOTH ``j.crew_id`` AND the
    // ``_crew_role`` value so direct-assigned non-crew jobs
    // (``crew_id=null``) stay chipless.
    expect(CODE).toMatch(/j\.crew_id\s*&&\s*\(?j\._crew_role\s*===\s*"direct"\s*\|\|\s*j\._crew_role\s*===\s*"member"\)?/);
  });

  it("ships the schedule-card-crew-badge-<id> data-testid", () => {
    expect(CODE).toMatch(
      /data-testid=\{`schedule-card-crew-badge-\$\{j\.id\}`\}/,
    );
  });

  it("stamps data-crew-role for e2e selectors", () => {
    expect(CODE).toMatch(/data-crew-role=\{j\._crew_role\}/);
  });

  it("wires 'Crew lead' copy to _crew_role === 'direct'", () => {
    // The ternary emits "Crew lead" for direct and "Crew member"
    // for every other allowed value (only ``member`` reaches this
    // branch given the outer gate).
    expect(CODE).toMatch(
      /j\._crew_role\s*===\s*"direct"\s*\?\s*"Crew lead"\s*:\s*"Crew member"/,
    );
  });

  it("sets the chip title to a role-specific tooltip", () => {
    expect(CODE).toMatch(/You lead this crew job/);
    expect(CODE).toMatch(/You're a member of the crew on this job/);
  });

  it("renders the Users icon inside the chip", () => {
    // The icon must appear within the badge JSX, not somewhere
    // else on the page — assert the sibling-order marker.
    expect(CODE).toMatch(/<Users size=\{9\}\s*\/?>[\s\S]{0,80}Crew lead/);
  });

  it("suppresses the chip when _crew_role is null/undefined (admin / non-tech view)", () => {
    // The ternary ends with ``: null`` so admins (whose
    // ``_crew_role=null`` server-side) render nothing.
    // Locate the badge's closing ternary — must end in ``: null }``.
    expect(CODE).toMatch(/schedule-card-crew-badge-\$\{j\.id\}[\s\S]*?:\s*null\}/);
  });
});
