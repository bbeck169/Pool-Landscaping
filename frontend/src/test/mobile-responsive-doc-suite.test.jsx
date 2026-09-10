/**
 * Feb-2026 · Universal mobile-responsive redesign · Vitest matrix.
 *
 * Aligned to the Feb-2026 mobile design reference:
 *   1. Dark banner + uppercase doc-type label.
 *   2. Full-width green primary CTA with the amount interpolated.
 *      Signature-gate disables the CTA + renders an amber hint.
 *      Estimate / quote surfaces render an outlined Decline CTA
 *      and a plain-text Request Changes link below.
 *   3. Two-column business info block (logo + brand name + tel
 *      link  |  doc # + due / valid-until date).
 *   4. Compact table rows for line items with declined chip +
 *      icon-only decline / undecline button preserved.
 *   5. Totals block with dashed divider + original/adjusted split
 *      when ``has_declined_lines=true``.
 *   6. Sticky action bar retained as a scaffold (used by future
 *      surfaces if the top CTA proves insufficient).
 *   7. Hook: ``useViewportBreakpoint`` SSR safety.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, renderHook, act } from "@testing-library/react";

import useViewportBreakpoint from "@/hooks/useViewportBreakpoint";
import DocLineItemCard from "@/components/documents/DocLineItemCard";
import DocTotalsBlock from "@/components/documents/DocTotalsBlock";
import DocStickyActionBar from "@/components/documents/DocStickyActionBar";
import DocMobileHeader from "@/components/documents/DocMobileHeader";
import DocTermsSection from "@/components/documents/DocTermsSection";


// ─── matchMedia mock helper ───────────────────────────────────────
function setMatchMedia(matches) {
  const listeners = new Set();
  Object.defineProperty(window, "matchMedia", {
    writable: true, configurable: true,
    value: vi.fn().mockImplementation((query) => ({
      matches,
      media: query,
      addEventListener: (_ev, cb) => listeners.add(cb),
      removeEventListener: (_ev, cb) => listeners.delete(cb),
      addListener: (cb) => listeners.add(cb),
      removeListener: (cb) => listeners.delete(cb),
      dispatchEvent: () => {},
      onchange: null,
    })),
  });
  return {
    fire: (nextMatches) => {
      window.matchMedia.mock.results.forEach((r) => {
        r.value.matches = nextMatches;
      });
      listeners.forEach((cb) => cb({ matches: nextMatches }));
    },
  };
}


beforeEach(() => { setMatchMedia(false); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });


// ─── 1. Hook ──────────────────────────────────────────────────────
describe("useViewportBreakpoint · SSR safety + reactive", () => {
  it("returns 'desktop' when matchMedia is unavailable", () => {
    // @ts-ignore
    delete window.matchMedia;
    const { result } = renderHook(() => useViewportBreakpoint());
    expect(result.current).toBe("desktop");
  });

  it("returns 'mobile' when matchMedia matches at mount", () => {
    setMatchMedia(true);
    const { result } = renderHook(() => useViewportBreakpoint());
    expect(result.current).toBe("mobile");
  });

  it("updates when matchMedia change fires", async () => {
    const ctrl = setMatchMedia(false);
    const { result } = renderHook(() => useViewportBreakpoint());
    expect(result.current).toBe("desktop");
    await act(async () => { ctrl.fire(true); });
    expect(result.current).toBe("mobile");
    await act(async () => { ctrl.fire(false); });
    expect(result.current).toBe("desktop");
  });
});


// ─── 2. DocLineItemCard (compact row) ─────────────────────────────
describe("DocLineItemCard · declined-state + compact row", () => {
  it("renders base row with testidPrefix + qty + total", () => {
    render(
      <DocLineItemCard
        line={{ description: "Pool clean", quantity: 4, total: 100 }}
        index={0} testidPrefix="estimate"
        fmt={(n) => `$${n}`}
      />,
    );
    const row = screen.getByTestId("estimate-line-item-card-0");
    expect(row).toBeTruthy();
    expect(row.getAttribute("data-customer-status")).toBe("pending");
    expect(row.textContent).toMatch(/Pool clean/);
    expect(row.textContent).toMatch(/\$100/);
  });

  it("renders declined chip + reason when customer_status='declined'",
    () => {
      render(
        <DocLineItemCard
          line={{
            description: "Filter",
            customer_status: "declined",
            customer_decline_reason: "still good",
            total: 50,
          }}
          index={1} testidPrefix="estimate"
          fmt={(n) => `$${n}`}
        />,
      );
      expect(screen.getByTestId("estimate-line-item-declined-chip-1"))
        .toBeTruthy();
      const reason = screen.getByTestId("estimate-line-item-decline-reason-1");
      expect(reason.textContent).toMatch(/still good/);
    });

  it("renders icon-only decline / undecline CTA when showDeclineButton=true",
    () => {
      const { rerender } = render(
        <DocLineItemCard
          line={{ description: "Pool clean", customer_status: "pending" }}
          index={0} testidPrefix="estimate"
          showDeclineButton
          onDecline={() => {}}
        />,
      );
      const declineBtn = screen.getByTestId("estimate-line-item-decline-0");
      expect(declineBtn).toBeTruthy();
      // Icon-only means aria-label present.
      expect(declineBtn.getAttribute("aria-label")).toMatch(/Decline/);

      rerender(
        <DocLineItemCard
          line={{ description: "Pool clean", customer_status: "declined" }}
          index={0} testidPrefix="estimate"
          showDeclineButton
          onUndecline={() => {}}
        />,
      );
      expect(screen.getByTestId("estimate-line-item-undecline-0")).toBeTruthy();
    });
});


// ─── 3. DocTotalsBlock ────────────────────────────────────────────
describe("DocTotalsBlock · defaults + adjusted-lines split", () => {
  it("derives default rows (subtotal, taxes, final)", () => {
    render(
      <DocTotalsBlock
        totals={{ subtotal: 100, taxes: 10, total: 110 }}
        testidPrefix="estimate"
      />,
    );
    expect(screen.getByTestId("estimate-totals-block")).toBeTruthy();
    expect(screen.getByTestId("estimate-totals-row-subtotal")).toBeTruthy();
    expect(screen.getByTestId("estimate-totals-row-taxes")).toBeTruthy();
    const final = screen.getByTestId("estimate-totals-row-final");
    expect(final.getAttribute("data-highlight")).toBe("true");
    expect(final.textContent).toMatch(/\$110/);
  });

  it("shows adjusted-total split row when has_declined_lines=true",
    () => {
      render(
        <DocTotalsBlock
          totals={{ subtotal: 100, total: 100, original_total: 200,
                    adjusted_total: 100, has_declined_lines: true,
                    declined_line_count: 2 }}
          testidPrefix="estimate"
        />,
      );
      const split = screen.getByTestId("estimate-totals-adjusted-row");
      expect(split).toBeTruthy();
      expect(screen.getByTestId("estimate-totals-original").textContent)
        .toMatch(/\$200/);
      expect(screen.getByTestId("estimate-totals-adjusted").textContent)
        .toMatch(/\$100/);
      const note = screen.getByTestId("estimate-totals-adjusted-note");
      expect(note.textContent).toMatch(/Adjusted for 2 declined line items/);
    });

  it("uses 'Balance due' as final label for invoices with balance_due",
    () => {
      render(
        <DocTotalsBlock
          totals={{ subtotal: 100, amount_paid: 30, balance_due: 70 }}
          testidPrefix="invoice"
        />,
      );
      const final = screen.getByTestId("invoice-totals-row-final");
      expect(final.textContent).toMatch(/Balance due/);
      expect(final.textContent).toMatch(/\$70/);
    });
});


// ─── 4. DocStickyActionBar (scaffold; not wired into surfaces) ────
describe("DocStickyActionBar · scaffold parity", () => {
  it("mobile: renders fixed positioning + full-width grid", () => {
    setMatchMedia(true);
    render(
      <DocStickyActionBar
        testid="test-bar"
        actions={[
          { key: "approve", label: "Approve", tone: "approve",
            testid: "act-approve", onClick: () => {} },
          { key: "decline", label: "Decline", tone: "decline",
            testid: "act-decline", onClick: () => {} },
        ]}
      />,
    );
    const bar = screen.getByTestId("test-bar");
    expect(bar.getAttribute("data-viewport")).toBe("mobile");
    expect(bar.style.position).toBe("fixed");
    expect(screen.getByTestId("act-approve")).toBeTruthy();
    expect(screen.getByTestId("act-decline")).toBeTruthy();
    expect(parseInt(screen.getByTestId("act-approve").style.minHeight))
      .toBeGreaterThanOrEqual(44);
  });

  it("desktop: renders inline flex (no fixed position)", () => {
    setMatchMedia(false);
    render(
      <DocStickyActionBar
        testid="test-bar-d"
        actions={[
          { key: "pay", label: "Pay", tone: "approve",
            testid: "act-pay", onClick: () => {} },
        ]}
      />,
    );
    const bar = screen.getByTestId("test-bar-d");
    expect(bar.getAttribute("data-viewport")).toBe("desktop");
    expect(bar.style.position).not.toBe("fixed");
  });
});


// ─── 5. DocMobileHeader ───────────────────────────────────────────
describe("DocMobileHeader · reference-aligned mobile top block", () => {
  it("estimate: dark banner + green CTA with amount + decline btn " +
     "+ two-col business info", () => {
    const onApprove = vi.fn();
    const onDecline = vi.fn();
    render(
      <DocMobileHeader
        docType="estimate"
        amount={425.99}
        company={{
          name: "Pool Co", phone: "(602) 555-1234",
          address: "1 Main St",
        }}
        docMeta={{ number: "EST-9", date: "2026-02-28" }}
        onPrimaryAction={onApprove}
        onDecline={onDecline}
        onRequestChanges={() => {}}
      />,
    );
    // Banner
    expect(screen.getByTestId("mobile-doc-banner")).toBeTruthy();
    expect(screen.getByTestId("mobile-doc-title").textContent)
      .toBe("ESTIMATE");
    // Primary CTA with amount
    const cta = screen.getByTestId("mobile-doc-primary-cta");
    expect(cta.textContent).toMatch(/Approve Estimate/);
    expect(cta.textContent).toMatch(/\$425\.99/);
    // Decline + Request Changes
    expect(screen.getByTestId("mobile-doc-decline-cta").textContent)
      .toMatch(/Decline Estimate/);
    expect(screen.getByTestId("mobile-doc-request-changes")).toBeTruthy();
    // Business info block
    const info = screen.getByTestId("mobile-doc-business-info");
    expect(info.textContent).toMatch(/Pool Co/);
    expect(info.textContent).toMatch(/1 Main St/);
    const tel = screen.getByTestId("mobile-doc-phone-link");
    expect(tel.getAttribute("href")).toMatch(/^tel:/);
    expect(screen.getByTestId("mobile-doc-doc-number").textContent)
      .toMatch(/Estimate #: EST-9/);
    expect(screen.getByTestId("mobile-doc-due-date").textContent)
      .toMatch(/Valid until: 2026-02-28/);
  });

  it("invoice: banner label INVOICE + green Pay Invoice CTA + no decline",
    () => {
    render(
      <DocMobileHeader
        docType="invoice"
        amount={42.82}
        company={{ name: "Pool Co" }}
        docMeta={{ number: "INV-42", date: "2026-03-01" }}
        onPrimaryAction={() => {}}
      />,
    );
    expect(screen.getByTestId("mobile-doc-title").textContent).toBe("INVOICE");
    const cta = screen.getByTestId("mobile-doc-primary-cta");
    expect(cta.textContent).toMatch(/Pay Invoice/);
    expect(cta.textContent).toMatch(/\$42\.82/);
    // Decline / Request Changes are hidden for invoices.
    expect(screen.queryByTestId("mobile-doc-decline-cta")).toBeNull();
    expect(screen.queryByTestId("mobile-doc-request-changes")).toBeNull();
    expect(screen.getByTestId("mobile-doc-doc-number").textContent)
      .toMatch(/Invoice #: INV-42/);
    expect(screen.getByTestId("mobile-doc-due-date").textContent)
      .toMatch(/Due: 2026-03-01/);
  });

  it("signature gate: disables Approve + renders amber hint + Sign now CTA",
    () => {
    const onSignNow = vi.fn();
    render(
      <DocMobileHeader
        docType="estimate"
        amount={100}
        company={{ name: "Pool Co" }}
        docMeta={{ number: "EST-1" }}
        onPrimaryAction={() => {}}
        onDecline={() => {}}
        primaryActionDisabled
        primaryActionHint="Sign to enable Approve"
        onSignNow={onSignNow}
      />,
    );
    const cta = screen.getByTestId("mobile-doc-primary-cta");
    expect(cta.disabled).toBe(true);
    expect(cta.getAttribute("data-signature-blocked")).toBe("true");
    const hint = screen.getByTestId("mobile-doc-primary-hint");
    expect(hint.textContent).toMatch(/Sign to enable/);
    expect(screen.getByTestId("mobile-approve-sign-now-cta")).toBeTruthy();
  });

  it("hasDeclinedLines=true swaps amount in CTA label to adjusted total",
    () => {
    render(
      <DocMobileHeader
        docType="estimate"
        amount={200}
        hasDeclinedLines
        adjustedAmount={100}
        company={{ name: "Pool Co" }}
        docMeta={{ number: "EST-2" }}
        onPrimaryAction={() => {}}
      />,
    );
    const cta = screen.getByTestId("mobile-doc-primary-cta");
    expect(cta.textContent).toMatch(/\$100\.00/);
    expect(cta.textContent).not.toMatch(/\$200\.00/);
  });

  it("preserves legacy testid aliases via data-legacy-testid attribute",
    () => {
    render(
      <DocMobileHeader
        docType="estimate"
        amount={100}
        company={{ name: "Pool Co" }}
        docMeta={{ number: "EST-1" }}
        onPrimaryAction={() => {}}
        onDecline={() => {}}
      />,
    );
    const cta = screen.getByTestId("mobile-doc-primary-cta");
    expect(cta.getAttribute("data-legacy-testid"))
      .toBe("estimate-toolbar-customer-approve");
    const decline = screen.getByTestId("mobile-doc-decline-cta");
    expect(decline.getAttribute("data-legacy-testid"))
      .toBe("estimate-toolbar-customer-decline");
  });
});


// ─── 6. DocTermsSection ───────────────────────────────────────────
describe("DocTermsSection · pre-built slot", () => {
  it("renders nothing when terms is empty", () => {
    const { container } = render(
      <DocTermsSection terms="" testidPrefix="estimate" />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders heading in brand color + paragraph body when terms present",
    () => {
    render(
      <DocTermsSection
        terms={"First para.\n\nSecond para."}
        brandColor="#0EA5E9"
        testidPrefix="estimate"
      />,
    );
    const el = screen.getByTestId("estimate-terms-section");
    expect(el).toBeTruthy();
    expect(el.textContent).toMatch(/Terms & Conditions/);
    expect(el.textContent).toMatch(/First para/);
    expect(el.textContent).toMatch(/Second para/);
  });
});
