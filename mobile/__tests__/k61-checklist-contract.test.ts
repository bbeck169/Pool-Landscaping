/**
 * K61.b.2 · Feb-2026 — Save-draft honesty contract assertions.
 *
 * Guards the ``flushSave`` refactor in
 * ``mobile/app/job/[id]/checklist.tsx`` against regressions.
 *
 * ``flushSave`` lives inside a ``useCallback`` closure and is called
 * by three surfaces (autosave debounce, explicit Save-draft, Close-
 * job pre-flush).  Full behavioral testing would require a rendered
 * ChecklistScreen with a mocked ``offlineWrite`` + ``writeQueue`` +
 * ``api.patch`` stack — heavy for a small contract fix.  This suite
 * instead locks in the STATIC contract:
 *
 *   1. Return type declared as ``Promise<FlushSaveResult>``.
 *   2. All three envelope shapes appear as literal return-values:
 *      - ``{ ok: true }``                — persisted / no-op
 *      - ``{ ok: true, queued: true }``  — offline write-queue path
 *      - ``{ ok: false, error: … }``     — HTTP failure / unexpected
 *   3. ``saveDraft`` reacts to ``result.ok`` and ``result.queued``
 *      instead of unconditionally showing "Saved" (pre-K61 bug).
 *   4. ``closeJob`` pre-flush respects the ``!flushed.ok`` short-
 *      circuit and NEVER proceeds to POST /submit on a failed
 *      pre-flush PATCH.
 *   5. The K61.c chemistry-gate branch is structural (``err instanceof
 *      ApiError`` + ``err.status === 422`` + ``err.detail.detail ===
 *      "chemistry_core_readings_missing"``) — NOT the pre-K61 dead
 *      axios-shape probe.
 *
 * See /app/memory/PHASE_K61_MOBILE_SAVE_CLOSE_ROBUSTNESS.md.
 */
import fs from "fs";
import path from "path";

const CHECKLIST = path.resolve(
  __dirname,
  "../app/job/[id]/checklist.tsx",
);

let source: string;
beforeAll(() => {
  source = fs.readFileSync(CHECKLIST, "utf8");
});

describe("K61.b.2 · flushSave return-envelope contract", () => {
  it("declares the ``FlushSaveResult`` type with ok + queued + error", () => {
    // TD-g2 — the type moved to src/lib/submittedReportUnlock.ts (adds
    // needsUnlock / blocked / cancelled); checklist imports it.
    const lib = fs.readFileSync(path.resolve(__dirname, "../src/lib/submittedReportUnlock.ts"), "utf8");
    expect(lib).toMatch(/type\s+FlushSaveResult\s*=\s*\{\s*ok:\s*boolean;\s*queued\?:\s*boolean;\s*error\?:\s*string;/);
    expect(source).toMatch(/type FlushSaveResult,?\s*\}\s*from\s*"@\/src\/lib\/submittedReportUnlock"/);
  });

  it("flushSave declares the return type as Promise<FlushSaveResult>", () => {
    expect(source).toMatch(/flushSave\s*=\s*useCallback\(\s*async\s*\(\s*\)\s*:\s*Promise<FlushSaveResult>/);
  });

  it("emits ``{ ok: true, queued: true }`` on the offline write-queue path", () => {
    expect(source).toMatch(/return\s*\{\s*ok:\s*true,\s*queued:\s*true\s*\}/);
  });

  it("emits ``{ ok: true }`` on the online happy-path", () => {
    // Locate the happy-path return specifically — not counting the
    // early-return short-circuits (which also emit `{ ok: true }` but
    // are guarded by `!current` / `submitted_at` / `!dirty`).
    const happyPathBlock = source.slice(source.indexOf("K61.b.2 · Feb-2026 — happy path"));
    expect(happyPathBlock).toMatch(/return\s*\{\s*ok:\s*true\s*\}/);
  });

  it("emits ``{ ok: false, error: … }`` on caught errors", () => {
    expect(source).toMatch(/return\s*\{\s*ok:\s*false,\s*error:/);
  });

  it("REGRESSION — no bare ``return;`` swallowing an error inside flushSave's catch", () => {
    // Pre-K61 the catch block did ``setSaveState("error"); return;`` —
    // meaning the caller never learned the operation failed and could
    // then unconditionally show a "Saved" toast.  The K61.b.2 fix
    // MUST have that catch return a { ok: false } envelope.
    const catchBlock = source.match(/\}\s*catch\s*\(e:\s*any\)\s*\{[^}]*setSaveState\("error"\)[^}]*\}/);
    expect(catchBlock).not.toBeNull();
    if (catchBlock) {
      expect(catchBlock[0]).toMatch(/return\s*\{\s*ok:\s*false,\s*error:/);
    }
  });
});

describe("K61.b.2 · saveDraft branches on the flushSave result", () => {
  it("awaits flushSave into a ``result`` variable and reads ``result.ok``", () => {
    // TD-g2 — saveDraft goes through runSave (flushSave + unlock orchestration).
    expect(source).toMatch(/const\s+result\s*=\s*await\s+runSave\(\)/);
    expect(source).toMatch(/if\s*\(\s*result\.ok\s*\)/);
  });

  it("shows the offline-queued affordance when ``result.queued`` is truthy", () => {
    expect(source).toMatch(/result\.queued/);
    expect(source).toMatch(/["']Saved locally["']/);
    expect(source).toMatch(/queued and will sync when your device reconnects/i);
  });

  it("shows a ``Save failed`` alert (NOT a ``Saved`` alert) on the !ok branch", () => {
    // Match against the exact saveDraft catch branch (the alert text
    // is unique so we can gate on it).
    expect(source).toMatch(/Alert\.alert\(\s*["']Save failed["']/);
  });

  it("REGRESSION — no unconditional ``Alert.alert(\"Saved\", \"Draft saved.\")`` post-flushSave", () => {
    // Pre-K61 saveDraft did:
    //   await flushSave();
    //   Alert.alert("Saved", "Draft saved.");
    // regardless of outcome — that lied to the tech on failure.  The
    // K61 fix guards the "Saved" alert behind `result.ok && !queued`.
    //
    // Assert the pre-K61 exact-sequence pattern no longer exists.
    expect(source).not.toMatch(/await\s+flushSave\(\);\s*Alert\.alert\(\s*["']Saved["']/);
  });
});

describe("K61.b.2 · closeJob pre-flush short-circuit", () => {
  it("captures flushSave's return into ``flushed`` and short-circuits on !flushed.ok", () => {
    // TD-g2 — pre-flush goes through runSave (flushSave + unlock orchestration).
    expect(source).toMatch(/const\s+flushed\s*=\s*await\s+runSave\(/);
    expect(source).toMatch(/if\s*\(\s*!flushed\.ok\s*\)/);
  });

  it("shows a ``Save failed`` alert and BAILS OUT before calling POST /submit on pre-flush failure", () => {
    // Locate the pre-flush block and check it contains the bailout.
    const preflushBlock = source.slice(source.indexOf("const flushed = await runSave("));
    expect(preflushBlock.slice(0, 800)).toMatch(/Alert\.alert\(\s*["']Save failed["']/);
    expect(preflushBlock.slice(0, 800)).toMatch(/setSubmitting\(false\)/);
    expect(preflushBlock.slice(0, 800)).toMatch(/return;/);
  });
});

describe("K61.a.2 + K61.c · closeJob structured chemistry-gate branch", () => {
  it("imports ApiError from @/src/api", () => {
    expect(source).toMatch(/import\s*\{[^}]*\bApiError\b[^}]*\}\s*from\s*["']@\/src\/api["']/);
  });

  it("imports expandChemistryLabel from @/src/lib/expandChemistryLabel", () => {
    expect(source).toMatch(/import\s*\{\s*expandChemistryLabel\s*\}\s*from\s*["']@\/src\/lib\/expandChemistryLabel["']/);
  });

  it("uses ``e instanceof ApiError`` for the structured branch", () => {
    expect(source).toMatch(/e\s+instanceof\s+ApiError/);
  });

  it("reads ``e.status === 422`` (structural) rather than ``e?.response?.status``", () => {
    expect(source).toMatch(/e\.status\s*===\s*422/);
  });

  it("gates the chemistry branch on ``detail === 'chemistry_core_readings_missing'``", () => {
    expect(source).toMatch(/detail\s*===\s*["']chemistry_core_readings_missing["']/);
  });

  it("REGRESSION — no ``e?.response?.data?.detail`` axios-shape probe left in closeJob's catch", () => {
    // The pre-K61 dead-code branch that never fired on the fetch-based
    // client.  Delete-and-forbid.
    expect(source).not.toMatch(/e\?\.response\?\.data\?\.detail/);
    expect(source).not.toMatch(/e\?\.response\?\.status/);
  });

  it("runs missing_labels through expandChemistryLabel before rendering the alert", () => {
    // The alert should show ``expandChemistryLabel(label)`` per K61.c.
    expect(source).toMatch(/missingLabels\.map\(expandChemistryLabel\)/);
  });

  it("wires ``setHighlightBodies`` for inline field highlighting (K61.c)", () => {
    // The pre-K61 code had the setHighlightBodies call but it never
    // fired because the outer if-branch was dead.  K61.c moves it
    // under the structural branch so it fires on real chemistry-gate
    // 422s.
    const catchBlock = source.slice(source.indexOf("K61.a.2 + K61.c"));
    expect(catchBlock.slice(0, 2500)).toMatch(/setHighlightBodies\(/);
  });
});
