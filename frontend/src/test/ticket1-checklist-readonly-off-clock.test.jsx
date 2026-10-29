// Ticket 1 · Feb-2026 — Routes/checklist opens read-only for
// off-the-clock landscape techs; mutations re-pop the clock-in
// dialog; successful clock-in flips the modal back to full edit.
//
// Source-inspection style (same pattern as
// ``k47-invoice-view-tracking.test.jsx`` + the Item #6 sent-column
// suite from last sprint) — the full ChecklistModal + schedule
// render tree depends on dozens of imports + API mocks and is
// locked separately by the K31 / K40 suites. Here we just lock
// the wiring contract so a future refactor can't silently
// regress the view-only path.

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(__dirname, "../../..");
const R = (rel) => readFileSync(resolve(ROOT, rel), "utf8");


describe("Ticket 1 · useClockInGate — openJob + requestMutation wiring", () => {
  const SRC = R("frontend/src/hooks/useClockInGate.jsx");

  it("exports requestMutation on the hook result", () => {
    // The returned object MUST include ``requestMutation`` so
    // callers can pop the clock-in dialog from inside the view-
    // only modal.
    expect(SRC).toMatch(/return\s*\{[^}]*requestMutation[^}]*\}/);
  });

  it("openJob calls back with {readOnly} on BOTH clocked-in and off-clock", () => {
    // Clocked-in branch — readOnly: false.
    expect(SRC).toMatch(/cb\({ readOnly: false }\)/);
    // Off-clock branch — readOnly: true (clocked-in = false ⇒
    // readOnly true).
    expect(SRC).toMatch(/cb\({ readOnly: !clockedIn }\)/);
  });

  it("off-clock openJob does NOT setPendingJob (no auto-dialog)", () => {
    // Legacy behaviour: off-clock openJob called setPendingJob
    // immediately, which popped the dialog. Ticket 1 flips that:
    // off-clock now opens the modal view-only, and the dialog is
    // only popped on an explicit mutation attempt.
    //
    // Lock: the ``cb ? cb({readOnly: !clockedIn})`` short-circuit
    // precedes any setPendingJob call inside openJob — meaning
    // if a caller passes a cb (every real caller does today),
    // setPendingJob is skipped.
    const openJobSrc = SRC.split("const openJob")[1].split("const requestMutation")[0];
    const cbReadOnlyIdx = openJobSrc.indexOf("cb({ readOnly: !clockedIn })");
    const setPendingIdx = openJobSrc.indexOf("setPendingJob");
    expect(cbReadOnlyIdx).toBeGreaterThan(-1);
    // Either setPendingJob is after the cb-readOnly branch (ternary
    // fallback for callers without cb) OR it's absent entirely from
    // the openJob block. Both are acceptable; the invariant is cb
    // is called BEFORE any setPendingJob dialog arming.
    if (setPendingIdx !== -1) {
      expect(setPendingIdx).toBeGreaterThan(cbReadOnlyIdx);
    }
  });

  it("requestMutation arms the dialog by setting pendingJob", () => {
    const reqSrc = SRC.split("const requestMutation")[1].split("const clockInAndProceed")[0];
    expect(reqSrc).toContain("setPendingJob");
    // Honors the onProceed callback so a successful clock-in can
    // flip the modal state.
    expect(reqSrc).toMatch(/cb:\s*onProceed/);
  });

  it("non-gated callers get a pass-through on requestMutation", () => {
    const reqSrc = SRC.split("const requestMutation")[1].split("const clockInAndProceed")[0];
    // Defensive branch for non-landscape users who shouldn't see
    // the dialog at all.
    expect(reqSrc).toMatch(/if\s*\(!gated\)/);
    expect(reqSrc).toMatch(/onProceed\?\.\(\)/);
  });
});


describe("Ticket 1 · ChecklistModal — view-only prop + mutation gates", () => {
  const SRC = R("frontend/src/components/checklist/ChecklistModal.jsx");

  it("accepts readOnly + onMutationBlocked props", () => {
    expect(SRC).toMatch(
      /export default function ChecklistModal\({[^}]*readOnly[^}]*onMutationBlocked[^}]*}\)/,
    );
  });

  it("defines _blockMutation that invokes onMutationBlocked", () => {
    expect(SRC).toContain("const _blockMutation = useCallback");
    expect(SRC).toContain("onMutationBlocked?.()");
  });

  it("gates patchReport (all chip/field edits route through it)", () => {
    const sliced = SRC.split("const patchReport")[1].split("const handleReclassify")[0];
    expect(sliced).toMatch(/if\s*\(readOnly\)/);
    expect(sliced).toContain("_blockMutation()");
    expect(sliced).toContain("return");
  });

  it("gates handleReclassify", () => {
    const sliced = SRC.split("const handleReclassify")[1].split("const saveDraft")[0];
    expect(sliced).toMatch(/if\s*\(readOnly\)/);
    expect(sliced).toContain("_blockMutation()");
  });

  it("gates saveDraft", () => {
    const sliced = SRC.split("const saveDraft")[1].split("const closeJob")[0];
    expect(sliced).toMatch(/if\s*\(readOnly\)/);
    expect(sliced).toContain("_blockMutation()");
  });

  it("gates closeJob", () => {
    const sliced = SRC.split("const closeJob")[1].split("const _closeJob")[0]
      // ``closeJob`` is the top-level function; split at the next
      // ``const `` so the slice stays bounded even if the file
      // adds a sibling helper later.
      || SRC.split("const closeJob")[1];
    expect(sliced).toMatch(/if\s*\(readOnly\)/);
    expect(sliced).toContain("_blockMutation()");
  });

  it("gates the autosave-retry button", () => {
    expect(SRC).toMatch(/if\s*\(readOnly\)\s*\{\s*_blockMutation\(\);\s*return;/);
  });
});


describe("Ticket 1 · CalendarSchedule wires the view-only path", () => {
  const SRC = R("frontend/src/pages/schedule/CalendarSchedule.jsx");

  it("has a checklistReadOnly state cell", () => {
    expect(SRC).toContain("const [checklistReadOnly, setChecklistReadOnly]");
  });

  it("destructures {readOnly} from the openJob callback (primary tap)", () => {
    // The onSelectEvent primary opener — Calendar tap target.
    expect(SRC).toMatch(
      /clockGate\.openJob\(ev\.id,\s*\(\{\s*readOnly\s*\}\)\s*=>/,
    );
  });

  it("destructures {readOnly} from the openJob callback (grid onOpenJob prop)", () => {
    // The Grid tap target routes through the ``onOpenJob`` prop.
    expect(SRC).toMatch(
      /onOpenJob=\{\(id\)\s*=>\s*clockGate\.openJob\(id,\s*\(\{\s*readOnly\s*\}\)\s*=>/,
    );
  });

  it("threads readOnly + onMutationBlocked into <ChecklistModal>", () => {
    const modalBlock = SRC.split("<ChecklistModal")[1].split("/>")[0];
    expect(modalBlock).toContain("readOnly={checklistReadOnly}");
    expect(modalBlock).toContain("onMutationBlocked={");
    expect(modalBlock).toContain("clockGate.requestMutation(");
    // Successful clock-in flips the modal back to editable in-place.
    expect(modalBlock).toContain("setChecklistReadOnly(false)");
  });

  it("resets checklistReadOnly to false on close", () => {
    const modalBlock = SRC.split("<ChecklistModal")[1].split("/>")[0];
    expect(modalBlock).toMatch(/setChecklistReadOnly\(false\)[\s\S]*onSubmitted|onClose=\{/);
  });
});
