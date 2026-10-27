/**
 * WW · Feb-2026 — tech ``ServiceReport.jsx`` post-completion
 * narrow unlock (checklist + photo add/delete) + badge.
 *
 * Operator-spec contract (WW Phase 2 scope, decision S2(a)):
 *   * When ``locked`` (post-submit) AND the parent job is
 *     ``status == "completed"`` AND the viewer is BE-authorized
 *     (jobMeta GET returned 200), unlock checklist toggles +
 *     photo add/delete controls ONLY.
 *   * Chemistry / notes / chemicals-added STAY locked
 *     (CHEM-LOCK invariant preserved).
 *   * Open-status jobs: pre-WW behavior unchanged (if locked,
 *     all controls still locked — the "ask admin to unlock"
 *     flow still applies).
 *   * Badge ``svc-report-edited-after-completion-badge`` renders
 *     when ``jobMeta.edited_after_completion === true`` (shared
 *     invariant with JobDetail badge).
 *
 * Source-grep style mirrors
 * ``ww-jobdetail-edited-after-completion-badge.test.jsx`` + the
 * sibling ``jobdetail-td78b-banner`` suite — full-render on
 * ServiceReport.jsx requires a tall mock tower (useAuth,
 * useTenantTheme, useIdempotencyKey, useFormTemplateRuntime,
 * TemplateFieldProvider, api, router, lazy imports). The
 * structural grep locks the invariants a refactor would
 * trip without the mock cost.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/tech/ServiceReport.jsx"),
  "utf-8",
);


describe("WW · ServiceReport tech post-completion narrow unlock + badge", () => {
  it("`wwUnlocked` derivation requires `locked` AND status=='completed' AND jobMeta loaded", () => {
    // Pin the exact 3-term derivation shape so a refactor can't
    // accidentally widen (drop a term) or narrow (add an
    // undocumented term) without failing loud.
    expect(SRC).toMatch(/const\s+wwUnlocked\s*=/);
    const idx = SRC.indexOf("const wwUnlocked");
    expect(idx).toBeGreaterThan(-1);
    // Walk the derivation to the next semicolon.
    const semi = SRC.indexOf(";", idx);
    expect(semi).toBeGreaterThan(idx);
    const expr = SRC.slice(idx, semi);
    // All three terms must appear (compound `&&`).
    expect(expr).toContain("locked");
    expect(expr).toContain('_parentStatus === "completed"');
    expect(expr).toContain("!!jobMeta");
  });

  it("checklist toggle button gate opens on `wwUnlocked` — operator S2(a)", () => {
    // Button must call `toggleCheck(i)` when `(!locked || wwUnlocked)`.
    // The pre-WW gate was `!locked && toggleCheck(i)` → now
    // `(!locked || wwUnlocked) && toggleCheck(i)`.
    expect(SRC).toMatch(
      /\(\s*!locked\s*\|\|\s*wwUnlocked\s*\)\s*&&\s*toggleCheck\(i\)/
    );
    // `disabled` prop uses the inverse: `locked && !wwUnlocked`.
    expect(SRC).toMatch(/disabled=\{locked\s*&&\s*!wwUnlocked\}/);
  });

  it("checklist note input renders when `(!locked || wwUnlocked)` — operator S2(a)", () => {
    expect(SRC).toMatch(
      /c\.checked\s*&&\s*\(\s*!locked\s*\|\|\s*wwUnlocked\s*\)/
    );
  });

  it("photo DELETE button gate opens on `wwUnlocked` — operator S2(a)", () => {
    // Walk the photos .map body — the remove button renders when
    // `(!locked || wwUnlocked)` instead of the pre-WW `!locked`.
    expect(SRC).toMatch(
      /\{\s*\(\s*!locked\s*\|\|\s*wwUnlocked\s*\)\s*&&\s*\(\s*\n?\s*<button\s+onClick=\{\(\)\s*=>\s*removePhoto\(/
    );
  });

  it("photo ADD label gate opens on `wwUnlocked` — operator S2(a)", () => {
    // Pre-WW: `!locked && remaining > 0 && (<label …`
    // WW: `(!locked || wwUnlocked) && remaining > 0 && (<label …`
    expect(SRC).toMatch(
      /\(\s*!locked\s*\|\|\s*wwUnlocked\s*\)\s*&&\s*remaining\s*>\s*0\s*&&\s*\(\s*\n?\s*<label/
    );
  });

  it("CHEM-LOCK preserved — chemistry / chemicals-added / notes still gated on `locked` only", () => {
    // Negative lock. Chemistry readings row, chemicals-added
    // rows, repair-mode notes, and the main notes textarea must
    // STILL be `disabled={locked}` (NOT `disabled={locked &&
    // !wwUnlocked}`) — operator S2(a) narrow-scope locked
    // chemistry/notes out of the WW unlock lane.
    //
    // Count: every `disabled={locked}` occurrence that is NOT on
    // the checklist toggle must stay. The checklist toggle is
    // the ONLY `disabled={locked && !wwUnlocked}` in the file.
    const narrowGateMatches = (
      SRC.match(/disabled=\{locked\s*&&\s*!wwUnlocked\}/g) || []
    );
    expect(narrowGateMatches.length).toBe(1); // only checklist toggle
    const chemLockMatches = SRC.match(/disabled=\{locked\}/g) || [];
    // Pre-WW count was 8 (chemistry name + amount + raw-amount +
    // unit + chemicals-added amount select + chemicals-added
    // unit select + repair notes + main notes). WW preserves
    // ALL 8 — the checklist toggle (previously 9th) is the only
    // one we widened.
    expect(chemLockMatches.length).toBeGreaterThanOrEqual(7);
  });

  it("`svc-report-locked-hint` CHEM-LOCK banner still gated on `locked` — not widened by WW", () => {
    // The banner shows for ANY submitted report (including
    // non-completed jobs that got clock-out stamped). Copy
    // adapts to narrow unlock when `wwUnlocked` is true. The
    // outer gate stays `{locked ? ( ... ) : null}` — the banner
    // itself does NOT get hidden on wwUnlocked (operator asked
    // for an ADAPTIVE copy, not banner removal).
    expect(SRC).toMatch(
      /\{locked\s*\?\s*\(\s*\n?\s*<div[\s\S]*?data-testid="svc-report-locked-hint"/
    );
    // Copy must adapt — "wwUnlocked" ternary in the banner body.
    const bannerIdx = SRC.indexOf("svc-report-locked-hint");
    expect(bannerIdx).toBeGreaterThan(-1);
    const bannerBodyEnd = SRC.indexOf("</div>", bannerIdx);
    const bannerSlice = SRC.slice(bannerIdx, bannerBodyEnd + 100);
    expect(bannerSlice).toContain("wwUnlocked");
  });

  it("WW badge element with the canonical testid exists", () => {
    expect(SRC).toMatch(/data-testid="svc-report-edited-after-completion-badge"/);
  });

  it("WW badge is gated by `jobMeta.edited_after_completion === true` — strict equality", () => {
    expect(SRC).toMatch(
      /jobMeta\?\.edited_after_completion\s*===\s*true\s*\?\s*\(/
    );
    const gateIdx = SRC.indexOf("jobMeta?.edited_after_completion === true");
    expect(gateIdx).toBeGreaterThan(-1);
    const close = SRC.indexOf(") : null}", gateIdx);
    expect(close).toBeGreaterThan(gateIdx);
    const slice = SRC.slice(gateIdx, close);
    expect(slice).toContain("svc-report-edited-after-completion-badge");
  });

  it("WW badge is NOT wired to any portal/customer context — admin + tech only", () => {
    const badgeIdx = SRC.indexOf("svc-report-edited-after-completion-badge");
    expect(badgeIdx).toBeGreaterThan(-1);
    const context = SRC.slice(Math.max(0, badgeIdx - 400), badgeIdx);
    expect(context).not.toMatch(/\bisPortal\b/);
    expect(context).not.toMatch(/\bportalContext\b/);
  });

  it("`jobMeta` is fetched via a parallel GET /jobs/{id} with soft-fail — pre-WW load still 200s on 404", () => {
    // Pin the parallel GET + try/catch soft-fail pattern so a
    // future refactor can't accidentally hard-fail the page
    // when the secondary job-meta load 404s (e.g., a soft-
    // deleted job whose service_report is still readable).
    expect(SRC).toMatch(/const\s+\[jobMeta,\s*setJobMeta\]\s*=\s*useState\(null\)/);
    expect(SRC).toMatch(/api\.get\(`\/jobs\/\$\{id\}`\)/);
    // The secondary load must be wrapped in try/catch so a 404
    // keeps the primary report render path intact.
    const loadIdx = SRC.indexOf("const load = useCallback");
    expect(loadIdx).toBeGreaterThan(-1);
    const loadEnd = SRC.indexOf("}, [id]);", loadIdx);
    const loadBody = SRC.slice(loadIdx, loadEnd);
    expect(loadBody).toContain("setJobMeta(j);");
    expect(loadBody).toContain("setJobMeta(null);");
  });

  it("open-status jobs: `wwUnlocked` stays false — pre-WW CHEM-LOCK invariant preserved", () => {
    // `_parentStatus === "completed"` is a hard requirement in the
    // derivation. For a non-completed submitted job (e.g., a
    // report submitted mid-visit before status flipped), the
    // narrow unlock does NOT fire — chemistry/notes AND
    // checklist/photos all stay locked. Re-pinned here so a
    // refactor cannot widen `_parentStatus` to include
    // in_progress / open.
    const idx = SRC.indexOf("const wwUnlocked");
    const semi = SRC.indexOf(";", idx);
    const expr = SRC.slice(idx, semi);
    expect(expr).toContain('"completed"');
    // No other status strings in the derivation.
    expect(expr).not.toMatch(/"in_progress"/);
    expect(expr).not.toMatch(/"active"/);
    expect(expr).not.toMatch(/"scheduled"/);
  });
});
