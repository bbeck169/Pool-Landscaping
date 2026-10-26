/**
 * Ticket FF · Feb-2026 — `getInvoiceDisplayTitle` case reorder.
 *
 * Pre-FF order (Ticket E · 5-case):
 *   1. invoice.title (verbatim)
 *   2. line_items[0].item_name
 *   3. line_items[0].name
 *   4. line_items[0].description (truncated)
 *   5. "" (blank)
 *
 * Post-FF order (operator revised Feb-2026):
 *   1. line_items[0].item_name           (was case 2)
 *   2. line_items[0].name                (was case 3)
 *   3. invoice.title (verbatim)          (was case 1)
 *   4. line_items[0].description trunc'd (unchanged)
 *   5. "" (blank)                        (unchanged)
 *
 * This test locks the ONE behavioural change that matters for FF —
 * when BOTH ``invoice.title`` AND ``line_items[0].item_name`` /
 * ``line_items[0].name`` are populated, the line-item name wins.
 * The pre-existing 23-case suite in
 * ``td-customer-profile-invoices-tab.test.jsx`` continues to pass
 * because each of those test inputs populates only one fallback
 * path at a time (verified green on reorder).
 */
import { describe, it, expect } from "vitest";
import { getInvoiceDisplayTitle } from "@/utils/invoiceTitle";

describe("Ticket FF · line-item name wins over invoice.title", () => {
  it("item_name wins over title (both populated)", () => {
    // Pre-FF: returned "Import #42" (title case 1 fired first).
    // Post-FF: returns "Weed Spray Service" (item_name case 1).
    expect(getInvoiceDisplayTitle({
      title: "Import #42",
      line_items: [{ item_name: "Weed Spray Service",
                     description: "Weekly spray x4" }],
    })).toBe("Weed Spray Service");
  });

  it("name wins over title (item_name absent, both others populated)", () => {
    expect(getInvoiceDisplayTitle({
      title: "Weekly Service",
      line_items: [{ name: "Pool opening" }],
    })).toBe("Pool opening");
  });

  it("title still returned when line_items empty (case 3 fallback)", () => {
    // This is the 96% preview reality — line_items[0] has no
    // item_name/name, so title still wins just like before FF.
    expect(getInvoiceDisplayTitle({
      title: "Weekly Service",
      line_items: [{ description: "Weekly cleaning x4" }],
    })).toBe("Weekly Service");
  });

  it("title still returned when line_items missing entirely", () => {
    expect(getInvoiceDisplayTitle({ title: "Monthly plan" }))
      .toBe("Monthly plan");
  });

  it("Import #<N> title bypassed when line_items has item_name", () => {
    // Explicit retroactive-import scenario the FF brief calls out.
    expect(getInvoiceDisplayTitle({
      title: "Import #259",
      line_items: [{ item_name: "Weekly Pool Service" }],
    })).toBe("Weekly Pool Service");
  });

  it("Import #<N> title still shows when line_items has no name", () => {
    // Expected fallthrough per FF brief: "Fallback behavior same
    // as Part 1" — no line_item name available → title displayed.
    expect(getInvoiceDisplayTitle({
      title: "Import #259",
      line_items: [{ description: "Weekly service bundle" }],
    })).toBe("Import #259");
  });
});
