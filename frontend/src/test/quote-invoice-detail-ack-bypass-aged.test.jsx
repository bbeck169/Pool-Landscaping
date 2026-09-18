/**
 * Feb 2026 · Follow-up — QuoteInvoiceDetail ack-bypass locked-list
 * widened to include ``past_due`` / ``unpaid`` / ``overdue`` so
 * admin / super_admin operators can correct aged-status invoices
 * without a void-and-re-issue.
 *
 * Static source-lint over the two _locked arrays (K71 line-items
 * inline save + Terms & Conditions inline save) — matches the
 * project's convention of contract-locking string arrays via file
 * grep (see p0-bug-b-pay-now-cta.test.jsx, invoice-pay-now-restyle
 * .test.jsx) rather than mounting the full router-heavy detail
 * page.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/quotes/QuoteInvoiceDetail.jsx"),
  "utf8",
);


describe("QuoteInvoiceDetail · ack-bypass locked-list widened", () => {
  it("K71 line-items save uses the widened _locked array", () => {
    // The block that gates the K71 editor's inline PUT lives right
    // before ``setPendingLines(nextLines)``. Assert the array
    // literal contains all 6 statuses in either legacy order.
    const idx = SRC.indexOf("setPendingLines(nextLines)");
    expect(idx).toBeGreaterThan(-1);
    // Grab a ~800-char window BEFORE the setPendingLines call — the
    // _locked declaration sits in that block.
    const before = SRC.slice(Math.max(0, idx - 800), idx);
    for (const status of ["sent", "accepted", "paid",
                            "past_due", "unpaid", "overdue"]) {
      expect(
        before.includes(`"${status}"`),
        `K71 _locked block missing "${status}"`,
      ).toBe(true);
    }
  });

  it("Terms editor save uses the widened _locked array", () => {
    // The second _locked declaration is inside the terms editor's
    // Save-button onClick handler — anchored on the sentinel
    // ``setPendingLines({ __terms__: termsDraft })``.
    const idx = SRC.indexOf("__terms__: termsDraft");
    expect(idx).toBeGreaterThan(-1);
    const before = SRC.slice(Math.max(0, idx - 800), idx);
    for (const status of ["sent", "accepted", "paid",
                            "past_due", "unpaid", "overdue"]) {
      expect(
        before.includes(`"${status}"`),
        `Terms editor _locked block missing "${status}"`,
      ).toBe(true);
    }
  });

  it("both _locked arrays share the exact same 6 statuses", () => {
    // Regression guard — future edits that update one array but
    // forget the other will fail here. Match both arrays via a
    // targeted regex + assert equality of the resulting sets.
    const re = /const _locked = \[([^\]]*)\]\.includes\(_st\)/g;
    const matches = [...SRC.matchAll(re)];
    expect(matches.length).toBeGreaterThanOrEqual(2);
    const sets = matches.map((m) =>
      Array.from(m[1].matchAll(/"([a-z_]+)"/g))
        .map((mm) => mm[1])
        .sort()
        .join(","),
    );
    // Every _locked array must contain the identical widened list.
    for (const s of sets) {
      expect(s).toBe(sets[0]);
    }
    expect(sets[0]).toBe(
      ["accepted", "overdue", "paid", "past_due", "sent", "unpaid"]
        .join(","),
    );
  });

  it("EditLockConfirmDialog is imported so the ack popup can surface", () => {
    // Non-admin users don't reach the K71 editor save (it's gated
    // upstream by ``canEdit={isStaff && ...}``), so surfacing the
    // dialog for the widened statuses only requires that the dialog
    // component is still wired into the page.
    expect(SRC).toMatch(/import EditLockConfirmDialog from/);
  });

  it("canEdit gate excludes non-staff roles (regression guard)", () => {
    // Non-admin users must not see the K71 editor edit affordance
    // in the first place. This gate is what makes the "regular
    // non-admin roles: unchanged" clause of the ticket hold.
    expect(SRC).toMatch(/canEdit=\{[\s\S]{0,80}isStaff/);
  });

  it("isStaff is admin OR super_admin — no widening slipped in", () => {
    // Locks the staff-role gate exactly so a future edit that adds
    // ``technician`` (or worse, drops the gate) fails CI. The two
    // widened _locked arrays give admins a bigger footprint —
    // ``isStaff`` must stay narrow.
    expect(SRC).toMatch(
      /isStaff = \["admin", "super_admin"\]\.includes\(String\(user\?\.role \|\| ""\)\)/,
    );
  });
});
