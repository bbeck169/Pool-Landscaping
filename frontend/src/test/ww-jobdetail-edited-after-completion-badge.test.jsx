/**
 * WW · Feb-2026 — "Edited after completion" badge on ``JobDetail.jsx``.
 *
 * Operator-spec contract (WW Phase 2 scope):
 *   * Badge renders only when ``job.edited_after_completion === true``.
 *   * Badge sits ALONGSIDE the two existing K6 banners
 *     (``jd-closed-job-edits-logged-banner`` + ``jd-k6-edit-
 *     after-completion-banner``). The K6 banners are PRE-edit
 *     "editable" cues; this new badge is the POST-edit "has been
 *     edited" cue — operator decision S3(a).
 *   * Badge is admin + tech visible; NOT surfaced to customer
 *     portal (Phase 1 audit verified ``PortalServiceReports.jsx``
 *     has zero reads of this denorm).
 *   * Non-dismissible — the operator did not ask for a dismiss
 *     affordance, so pin the structural contract against a
 *     future refactor adding one.
 *
 * Source-grep style mirrors the sibling ``jobdetail-td78b-banner``
 * suite (K6 banner locks). Full-render would require a tall mock
 * tower (``useAuth``, ``useTenantTheme``, router, api, lazy
 * imports, PageHeader, StatusPill); the structural grep is the
 * pragmatic lock the existing JobDetail suite uses for the K6
 * banners already.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobDetail.jsx"),
  "utf-8",
);


describe("WW · 'Edited after completion' badge on JobDetail — structural locks", () => {
  it("badge element with the canonical testid exists", () => {
    expect(SRC).toMatch(/data-testid="jd-edited-after-completion-badge"/);
  });

  it("badge is gated by `job.edited_after_completion === true` — the WW BE denorm", () => {
    // The gate must be an EQUALS-TRUE check (not truthy), so a
    // stray non-boolean denorm value can't accidentally render
    // the badge. Mirrors the BE invariant where the denorm is
    // stored as a strict boolean True via $set.
    expect(SRC).toMatch(
      /job\.edited_after_completion\s*===\s*true\s*\?\s*\(/
    );
    // Walk the gate's truthy branch and confirm the badge testid
    // sits inside it.
    const gateIdx = SRC.indexOf("job.edited_after_completion === true");
    expect(gateIdx).toBeGreaterThan(-1);
    const close = SRC.indexOf(") : null}", gateIdx);
    expect(close).toBeGreaterThan(gateIdx);
    const slice = SRC.slice(gateIdx, close);
    expect(slice).toContain("jd-edited-after-completion-badge");
  });

  it("badge does NOT render when `edited_after_completion` is false / undefined / missing", () => {
    // Negative lock — the gate is strict `=== true`, so any
    // other value (false, undefined, null, string) must not
    // render. We re-pin the strict-equality shape above; this
    // test adds a shape-negative for any truthy-coerce rewrites.
    expect(SRC).not.toMatch(
      /job\.edited_after_completion\s*\?\s*\(/
    );
    expect(SRC).not.toMatch(
      /!!job\.edited_after_completion\s*\?\s*\(/
    );
    expect(SRC).not.toMatch(
      /Boolean\(job\.edited_after_completion\)\s*\?\s*\(/
    );
  });

  it("existing K6 banners still present alongside the badge — regression lock", () => {
    // The badge SITS ALONGSIDE the two K6 banners (operator S3(a)
    // — "does NOT subsume them"). All three testids must coexist
    // in the file; a future refactor removing either K6 banner
    // trips this guard.
    expect(SRC).toMatch(/data-testid="jd-closed-job-edits-logged-banner"/);
    expect(SRC).toMatch(/data-testid="jd-k6-edit-after-completion-banner"/);
    expect(SRC).toMatch(/data-testid="jd-edited-after-completion-badge"/);
  });

  it("badge is NOT inside a dismissal-state gate — pin against a future refactor adding dismiss UX", () => {
    // Negative lock — no ``setBadgeDismissed`` / ``badgeDismissed``
    // state hooks on this file (would indicate a dismiss toggle).
    expect(SRC).not.toMatch(/\bbadgeDismissed\b/);
    expect(SRC).not.toMatch(/\bsetBadgeDismissed\b/);
  });

  it("badge copy says 'Edited after completion' verbatim — pins the operator-visible string", () => {
    expect(SRC).toMatch(/Edited after completion/);
  });

  it("badge is NOT wired to any `isPortal` / portal-context branch — admin + tech only", () => {
    // The WW spec is literal: "NOT surfaced to customer portal".
    // No ``isPortal`` or ``context === "portal"`` conditional
    // can wrap or feed into the badge.
    const badgeIdx = SRC.indexOf("jd-edited-after-completion-badge");
    expect(badgeIdx).toBeGreaterThan(-1);
    // Walk 400 chars BEFORE the badge testid; if any portal/
    // customer-context branch gated it, we'd see the identifier.
    const context = SRC.slice(Math.max(0, badgeIdx - 400), badgeIdx);
    expect(context).not.toMatch(/\bisPortal\b/);
    expect(context).not.toMatch(/\bportalContext\b/);
    expect(context).not.toMatch(/role\s*===\s*"customer"/);
  });

  it("`canEditCompleted` gate is unchanged — K6 unlock set + status gate preserved (regression lock)", () => {
    // Pre-existing contract from the K6 and TD-78b suites. Re-
    // pinned here so WW's badge insertion did NOT drift the K6
    // role gate.
    expect(SRC).toMatch(
      /const\s+canEditCompleted\s*=\s*\n?\s*!isCustomer\s*\n?\s*&&\s*K6_UNLOCK_ROLES\.has\(\s*user\?\.role\s*\|\|\s*""\s*\)\s*\n?\s*&&\s*\(job\?\.status\s*===\s*"completed"\)/
    );
  });
});
