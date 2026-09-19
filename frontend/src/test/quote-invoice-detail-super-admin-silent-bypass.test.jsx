/**
 * Feb-2026 · Invoice God Mode — super_admin silent bypass surface.
 *
 * Locks the QuoteInvoiceDetail save-site contract so a super_admin
 * editing an invoice whose status is ``past_due`` / ``unpaid`` /
 * ``overdue`` never opens the ``EditLockConfirmDialog`` and never
 * sends ``acknowledged_lock_bypass: true`` on the PUT — the
 * server-side gate applies the role-based silent bypass and writes
 * a distinct audit line, so the frontend must stay quiet.
 *
 * Static source-lint over the two save sites (K71 line-items +
 * Terms editor Save button) — matches the convention already used
 * by ``quote-invoice-detail-ack-bypass-aged.test.jsx``. Cheaper +
 * more targeted than mounting the router-heavy detail page for
 * what is fundamentally a control-flow guard.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/quotes/QuoteInvoiceDetail.jsx"),
  "utf8",
);


describe("QuoteInvoiceDetail · super_admin silent-bypass surface", () => {
  // -----------------------------------------------------------------
  // 1 · Both save sites compute a role-scoped silent-bypass flag.
  // -----------------------------------------------------------------
  it("K71 line-items save computes _silentBypass from role + status", () => {
    // Anchor on the setPendingLines(nextLines) sentinel (identical
    // to the ack-bypass test file's approach). The _silentBypass
    // declaration sits inside the same onLinesUpdated block.
    const idx = SRC.indexOf("setPendingLines(nextLines)");
    expect(idx).toBeGreaterThan(-1);
    const before = SRC.slice(Math.max(0, idx - 1200), idx);
    // Role check is exactly super_admin (no widening to admin).
    expect(before).toMatch(/_role\s*===\s*"super_admin"/);
    // Status check enumerates only the three aged statuses.
    for (const status of ["past_due", "unpaid", "overdue"]) {
      expect(
        before.includes(`"${status}"`),
        `K71 silent-bypass block missing "${status}"`,
      ).toBe(true);
    }
    // Silent-bypass MUST NOT include out-of-scope statuses.
    for (const status of ["paid", "void", "sent", "accepted", "draft"]) {
      // Only assert on the silent-bypass conditional line — the
      // _locked array 20 lines up still contains "paid"/"sent"/etc.
      const silentLine = before.match(
        /_silentBypass\s*=[\s\S]*?includes\(_st\)/,
      );
      expect(silentLine, "silent-bypass declaration missing").not.toBeNull();
      expect(
        silentLine[0].includes(`"${status}"`),
        `silent-bypass expression must NOT include "${status}"`,
      ).toBe(false);
    }
  });

  it("Terms editor save computes _silentBypass from role + status", () => {
    // Anchor on the __terms__ sentinel to isolate the Terms editor's
    // onClick handler. Same shape as the K71 site.
    const idx = SRC.indexOf("__terms__: termsDraft");
    expect(idx).toBeGreaterThan(-1);
    const before = SRC.slice(Math.max(0, idx - 1200), idx);
    expect(before).toMatch(/_role\s*===\s*"super_admin"/);
    for (const status of ["past_due", "unpaid", "overdue"]) {
      expect(
        before.includes(`"${status}"`),
        `Terms silent-bypass block missing "${status}"`,
      ).toBe(true);
    }
  });

  // -----------------------------------------------------------------
  // 2 · Dialog is suppressed AND the ack flag is omitted on silent.
  // -----------------------------------------------------------------
  it("both save sites suppress the dialog when _silentBypass fires", () => {
    // Guard the exact conditional shape: the dialog only opens when
    // _locked AND !_silentBypass AND !lockBypassAcked. Any drift
    // (e.g. accidentally dropping the ``!_silentBypass`` clause)
    // would silently re-surface the popup for super_admin.
    const re = /if\s*\(\s*_locked\s*&&\s*!\s*_silentBypass\s*&&\s*!\s*lockBypassAcked\s*\)/g;
    const matches = [...SRC.matchAll(re)];
    expect(
      matches.length,
      "expected 2 dialog-guard conditionals (line-items + terms)",
    ).toBeGreaterThanOrEqual(2);
  });

  it("both save sites omit acknowledged_lock_bypass on the silent path", () => {
    // Symmetric guard: the PUT body only carries the ack flag when
    // _locked AND !_silentBypass. Silent bypass stays quiet so the
    // backend writes ``put_quote_status_super_admin_silent_bypass``
    // instead of the standard ack path.
    const re = /if\s*\(\s*_locked\s*&&\s*!\s*_silentBypass\s*\)\s*_body\.acknowledged_lock_bypass\s*=\s*true/g;
    const matches = [...SRC.matchAll(re)];
    expect(
      matches.length,
      "expected 2 payload-guard assignments (line-items + terms)",
    ).toBeGreaterThanOrEqual(2);
  });

  // -----------------------------------------------------------------
  // 3 · Regression guards on adjacent contracts.
  // -----------------------------------------------------------------
  it("silent-bypass declarations share the identical scope on both sites", () => {
    // Extract every occurrence of the silent-bypass assignment and
    // assert they all resolve to the same role+status envelope so a
    // future edit that widens one site can't silently drift.
    const re = /_silentBypass\s*=\s*_role\s*===\s*"super_admin"[\s\S]*?includes\(_st\)/g;
    const matches = [...SRC.matchAll(re)];
    expect(
      matches.length,
      "expected 2 _silentBypass declarations",
    ).toBeGreaterThanOrEqual(2);
    // Normalise whitespace before comparing.
    const norm = matches.map((m) => m[0].replace(/\s+/g, " "));
    for (const decl of norm) {
      expect(decl).toBe(norm[0]);
    }
  });

  it("regular admin behaviour is unchanged (dialog still surfaces)", () => {
    // With ``_role !== "super_admin"``, ``_silentBypass`` is false,
    // so ``_locked && !_silentBypass && !lockBypassAcked`` collapses
    // to the pre-silent-bypass gate ``_locked && !lockBypassAcked``.
    // Anchor on the K71 save block and assert the dialog still
    // opens via ``setLockDialogOpen(true)`` after the gate.
    const idx = SRC.indexOf("setPendingLines(nextLines)");
    const window = SRC.slice(idx, idx + 200);
    expect(window).toMatch(/setLockDialogOpen\(true\)/);
  });

  it("_locked array still covers the six ack-widen statuses", () => {
    // Regression on the earlier ack-widen — silent-bypass work
    // must NOT have narrowed the _locked list (admin path relies
    // on it). Reuse the same regex the ack-bypass test file uses.
    const re = /const _locked = \[([^\]]*)\]\.includes\(_st\)/g;
    const matches = [...SRC.matchAll(re)];
    expect(matches.length).toBeGreaterThanOrEqual(2);
    const sets = matches.map((m) =>
      Array.from(m[1].matchAll(/"([a-z_]+)"/g))
        .map((mm) => mm[1])
        .sort()
        .join(","),
    );
    for (const s of sets) {
      expect(s).toBe(
        ["accepted", "overdue", "paid", "past_due", "sent", "unpaid"]
          .join(","),
      );
    }
  });
});
