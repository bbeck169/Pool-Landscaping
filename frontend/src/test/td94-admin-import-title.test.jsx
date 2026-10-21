/**
 * TD-94 · Feb-2026 — Admin Invoices list `Import #<N>` →
 * first line item name · Vitest for
 * `resolveImportedInvoiceTitleFromLineItem`.
 *
 * Locks the admin-list resolver contract shipped by `td94b-fe`:
 *
 *   1. Non-imported invoice → returns `invoice.title` unchanged.
 *   2. Imported invoice (predicate matches `Import #<N>`) with
 *      a non-empty `line_items[0].title` → returns that title.
 *   3. Same with only `line_items[0].description` populated →
 *      returns the description.
 *   4. Imported invoice with empty `line_items[]` → falls back
 *      to the stored `Import #<N>` title for admin
 *      traceability (deliberately NOT the neutral `"Invoice"`
 *      used by the portal / customer-tile resolver — see
 *      `memory/td94_admin_invoice_title_audit.md` §4 for the
 *      two-surface split rationale).
 *   5. Imported invoice with whitespace-only item fields →
 *      falls back.
 *   6. Null / non-object / missing invoice → returns empty
 *      string (defensive branch, matches
 *      `resolvePortalInvoiceTitle`'s null-input posture).
 *
 * Scope-check specs:
 *
 *   7. Shares the `isImportedPlaceholderTitle` predicate with
 *      `resolvePortalInvoiceTitle` — a title that doesn't match
 *      the predicate (e.g. `"Pool service — March"`) must pass
 *      through unchanged even if `line_items[]` is populated.
 *   8. The resolver does NOT mutate the input invoice (display-
 *      time only).
 *
 * Sibling: `test/portal-invoice-title.test.jsx` covers the TD-71
 * portal 4-branch resolver.  This file is the admin 2-branch
 * sibling.
 */
import { describe, it, expect } from "vitest";
import {
  resolveImportedInvoiceTitleFromLineItem,
  isImportedPlaceholderTitle,
} from "@/lib/portalInvoiceTitle";


function _imported(fields = {}) {
  return { title: "Import #259", ...fields };
}


describe("TD-94 · resolveImportedInvoiceTitleFromLineItem", () => {
  // ─── 1 · Non-imported pass-through ─────────────────────────────
  it("returns original title unchanged on a non-imported invoice", () => {
    const inv = {
      title: "Pool service — March",
      line_items: [{ title: "Weekly chlorine" }],
    };
    expect(resolveImportedInvoiceTitleFromLineItem(inv))
      .toBe("Pool service — March");
  });

  // ─── 2 · Imported + line_items[0].title ───────────────────────
  it("returns line_items[0].title on imported invoice", () => {
    expect(
      resolveImportedInvoiceTitleFromLineItem(_imported({
        line_items: [
          { title: "Palm Tree Trimming", description: "monthly" },
          { title: "Edging" },
        ],
      })),
    ).toBe("Palm Tree Trimming");
  });

  // ─── 3 · Imported + line_items[0].description fallback ────────
  it("falls back to line_items[0].description when title is empty", () => {
    expect(
      resolveImportedInvoiceTitleFromLineItem(_imported({
        line_items: [{ title: "", description: "Lawn mow + edging" }],
      })),
    ).toBe("Lawn mow + edging");
    expect(
      resolveImportedInvoiceTitleFromLineItem(_imported({
        line_items: [{ description: "Hedge trim" }],  // no title key
      })),
    ).toBe("Hedge trim");
  });

  // ─── 4 · Imported + empty line_items → stored title fallback ──
  it("falls back to the stored Import #<N> title when line_items is empty", () => {
    expect(
      resolveImportedInvoiceTitleFromLineItem(_imported({
        line_items: [],
      })),
    ).toBe("Import #259");
    // Also: line_items missing entirely.
    expect(
      resolveImportedInvoiceTitleFromLineItem(_imported({})),
    ).toBe("Import #259");
    // Also: line_items is not an array (defensive).
    expect(
      resolveImportedInvoiceTitleFromLineItem(_imported({
        line_items: null,
      })),
    ).toBe("Import #259");
  });

  // ─── 5 · Whitespace-only item → stored title fallback ─────────
  it("falls back when line_items[0] carries whitespace-only strings", () => {
    expect(
      resolveImportedInvoiceTitleFromLineItem(_imported({
        line_items: [{ title: "   ", description: "" }],
      })),
    ).toBe("Import #259");
    expect(
      resolveImportedInvoiceTitleFromLineItem(_imported({
        line_items: [{ title: "", description: "   \t  " }],
      })),
    ).toBe("Import #259");
  });

  // ─── 6 · Null / non-object defensive branch ───────────────────
  it("returns empty string for null / non-object / missing input", () => {
    expect(resolveImportedInvoiceTitleFromLineItem(null)).toBe("");
    expect(resolveImportedInvoiceTitleFromLineItem(undefined)).toBe("");
    expect(resolveImportedInvoiceTitleFromLineItem("Import #1")).toBe("");
    expect(resolveImportedInvoiceTitleFromLineItem(0)).toBe("");
  });

  // ─── 7 · Non-matching title → pass-through even with items ────
  it("does NOT swap when title fails the Import-#<N> predicate", () => {
    // Guards against someone widening the predicate to catch
    // non-import titles.  The predicate is the SINGLE source of
    // "is this invoice imported" truth — a title like "Imported"
    // or "Import #" (no number) must NOT be rewritten.
    for (const title of [
      "Imported",
      "Import #",
      "Importation #259",
      "Internal note: Import #259 pending review",
      "",
    ]) {
      expect(isImportedPlaceholderTitle({ title })).toBe(false);
      expect(
        resolveImportedInvoiceTitleFromLineItem({
          title,
          line_items: [{ title: "This should NOT appear" }],
        }),
      ).toBe(title);
    }
  });

  // ─── 8 · Immutable w.r.t. the input invoice ──────────────────
  it("does not mutate the input invoice", () => {
    const inv = _imported({
      line_items: [{ title: "Palm Tree Trimming" }],
    });
    const snapshot = JSON.parse(JSON.stringify(inv));
    resolveImportedInvoiceTitleFromLineItem(inv);
    expect(inv).toEqual(snapshot);
  });
});
