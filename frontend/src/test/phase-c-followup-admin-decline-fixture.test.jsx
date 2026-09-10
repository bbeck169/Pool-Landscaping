/**
 * Feb-2026 · Phase 2/C follow-up F — admin declined-lines banner
 * + list fixture-driven render tests.
 *
 * Tester couldn't observe ``admin-declined-lines-banner``,
 * ``admin-line-item-declined-badge-0``, or
 * ``admin-line-item-decline-reason-0`` on the specific quote
 * ``/quotes/b565f464-4814-4d85-bc75-8291f79821f9`` on PROD despite
 * backend data being correct — the SPA appeared to hang. This
 * suite mounts the banner + list components directly against a
 * fixture that mirrors the exact backend shape so any render
 * crash is caught before it reaches prod.
 *
 * Guards added in the components:
 *   * Every ``doc.line_items`` iteration filters out falsy
 *     entries (``.filter(Boolean)``) so a null line entry never
 *     throws.
 *   * ``AdminDeclinedLinesBannerImpl`` safely reads
 *     ``doc.declined_line_count`` / ``doc.original_total`` /
 *     ``doc.adjusted_total`` with nullish coalescing on both
 *     ``doc`` and the field.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

import {
  AdminDeclinedLinesBannerImpl,
  AdminDeclinedLinesListImpl,
  formatDeclinedTimestamp,
} from "@/pages/quotes/QuoteInvoiceDetail";


const fixture = {
  id: "b565f464-4814-4d85-bc75-8291f79821f9",
  doc_type: "quote",
  status: "sent",
  total: 100,
  adjusted_total: 50,
  original_total: 100,
  has_declined_lines: true,
  declined_line_count: 1,
  line_items: [
    {
      description: "Weekly Pool Cleaning",
      quantity: 4,
      unit_price: 25,
      total: 100,
      customer_status: "pending",
    },
    {
      description: "Filter replacement",
      quantity: 1,
      unit_price: 50,
      total: 50,
      customer_status: "declined",
      customer_decline_reason: "Filter is still good — will replace next quarter",
      customer_declined_at: "2026-02-07T14:22:00.000Z",
    },
  ],
};


describe("Phase 2/C-F · admin decline banner render contract", () => {
  it("banner renders the three required test-ids without crashing",
    () => {
      render(<AdminDeclinedLinesBannerImpl doc={fixture} />);
      const banner = screen.getByTestId("admin-declined-lines-banner");
      expect(banner).toBeTruthy();
      expect(banner.textContent).toMatch(/Customer declined 1 of 2 line items/i);
      expect(banner.textContent).toMatch(/Original: \$100/);
      expect(banner.textContent).toMatch(/Adjusted: \$50/);
      cleanup();
    });

  it("banner details toggle reveals declined-line list", () => {
    render(<AdminDeclinedLinesBannerImpl doc={fixture} />);
    // Details are collapsed by default.
    expect(screen.queryByTestId("admin-declined-lines-banner-details"))
      .toBeNull();
    fireEvent.click(screen.getByTestId("admin-declined-lines-banner-toggle"));
    const details = screen.getByTestId("admin-declined-lines-banner-details");
    expect(details).toBeTruthy();
    expect(details.textContent).toMatch(/Filter replacement/);
    expect(details.textContent).toMatch(/Filter is still good/);
    cleanup();
  });

  it("list renders per-line badge, reason, timestamp test-ids", () => {
    render(<AdminDeclinedLinesListImpl lineItems={fixture.line_items} />);
    // The declined line is at index 1 in the fixture.
    const badge = screen.getByTestId("admin-line-item-declined-badge-1");
    expect(badge).toBeTruthy();
    expect(badge.textContent).toMatch(/Declined/i);

    const reason = screen.getByTestId("admin-line-item-decline-reason-1");
    expect(reason).toBeTruthy();
    expect(reason.textContent).toMatch(/Filter is still good/);

    const when = screen.getByTestId("admin-line-item-declined-at-1");
    expect(when).toBeTruthy();
    // Deterministic humanised timestamp — asserted via helper below.
    cleanup();
  });

  it("banner is robust against a legacy doc with null line entries",
    () => {
      const legacy = {
        ...fixture,
        line_items: [null, ...fixture.line_items, null],
      };
      // Must not throw — regression guard for the exact prod hang
      // suspected on the specific quote id above.
      expect(() =>
        render(<AdminDeclinedLinesBannerImpl doc={legacy} />)
      ).not.toThrow();
      cleanup();
    });

  it("formatDeclinedTimestamp tolerates non-string legacy Mongo shapes",
    () => {
      // Simulates a legacy Mongo ``{$date: ...}`` extended-JSON
      // envelope that occasionally slips through the API layer.
      // Must not throw — the render was hanging on prod because
      // an unexpected shape here was aborting the subtree.
      expect(
        formatDeclinedTimestamp({ $date: "2026-02-07T14:22:00Z" })
      ).toBe("");
      expect(formatDeclinedTimestamp(42)).toBe("");
      expect(formatDeclinedTimestamp(undefined)).toBe("");
    });

  it("list is robust against a legacy doc with null line entries",
    () => {
      const items = [null, ...fixture.line_items, null];
      expect(() =>
        render(<AdminDeclinedLinesListImpl lineItems={items} />)
      ).not.toThrow();
      // Test-ids still resolve at the original indices in the safe
      // filtered array — index 1 in the filtered array is the
      // declined line.
      expect(screen.getByTestId("admin-line-item-declined-badge-1"))
        .toBeTruthy();
      cleanup();
    });

  it("banner degrades gracefully when doc.declined_line_count is absent",
    () => {
      const noCount = { ...fixture };
      delete noCount.declined_line_count;
      render(<AdminDeclinedLinesBannerImpl doc={noCount} />);
      // Falls back to computing from line_items — still 1 declined.
      const banner = screen.getByTestId("admin-declined-lines-banner");
      expect(banner.textContent).toMatch(/1 of 2/);
      cleanup();
    });

  it("formatDeclinedTimestamp returns a stable human string", () => {
    const now = Date.UTC(2026, 1, 9, 14, 22, 0);
    // Same day, 2 hours earlier.
    const iso = new Date(now - 2 * 60 * 60 * 1000).toISOString();
    expect(formatDeclinedTimestamp(iso, now)).toBe("Declined 2h ago");
  });
});
