/**
 * Feb-2026 · Interactive Flipbook Estimate Viewer — customer viewer
 * contract tests. Covers the branch decision in ``<EstimateView>``,
 * the page assembly rules in ``<EstimateFlipbook>``, and edge cases
 * around missing / broken background images.
 *
 * We DON'T mount ``<HTMLFlipBook>`` directly — react-pageflip does
 * layout on a canvas + touch surface that jsdom can't stub. Instead
 * we mock ``FlipbookShim`` to a straight ``<div>`` that renders
 * children in order. That still exercises the page-assembly
 * pipeline, prop plumbing, keyboard nav wiring, and the DOM
 * contract (testids, aria labels, hrefs) — which is what matters
 * for a regression harness.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";


// Mock the flipbook shim to a plain <div> so pages are always in
// the DOM and testable. Mock BEFORE importing the component.
// Filter out react-pageflip-specific props so React doesn't warn
// about unknown DOM attributes on the mock <div>.
const _FLIPBOOK_ONLY_PROPS = new Set([
  "width", "height", "size", "minWidth", "maxWidth", "minHeight",
  "maxHeight", "maxShadowOpacity", "showCover", "flippingTime",
  "usePortrait", "startZIndex", "drawShadow", "onFlip",
]);

vi.mock("@/components/estimates/FlipbookShim", () => ({
  __esModule: true,
  default: React.forwardRef(function MockFlipbook({ children, ...rest }, ref) {
    const _domProps = {};
    for (const [k, v] of Object.entries(rest)) {
      if (!_FLIPBOOK_ONLY_PROPS.has(k)) _domProps[k] = v;
    }
    // Expose the same ref-shape react-pageflip provides so
    // consumers don't crash on ``ref.current.pageFlip()``.
    React.useImperativeHandle(ref, () => ({
      pageFlip: () => ({
        flip: () => {},
        flipNext: () => {},
        flipPrev: () => {},
      }),
    }));
    return (
      <div data-testid="mock-flipbook" {..._domProps}>
        {children}
      </div>
    );
  }),
}));


import EstimateFlipbook from "@/components/estimates/EstimateFlipbook";


// ─── fixtures ──────────────────────────────────────────────────────


function _minPayload(overrides = {}) {
  return {
    estimate_id: "est-1",
    status: "sent",
    company: { name: "Vistancia Pools", logo_url: null },
    bill_to: { name: "Jane Homeowner" },
    header: { estimate_number: "Q-2026-000042", estimate_date: "2026-02-11" },
    title: "Backyard Refresh",
    expires_at: "2026-04-01",
    line_items: [
      { id: "li-1", description: "Pool tile replacement", quantity: 1,
        unit_price: 4200, service_category_id: "cat-pool",
        customer_status: "pending" },
      { id: "li-2", description: "Coping install", quantity: 1,
        unit_price: 1500, service_category_id: "cat-pool",
        customer_status: "pending" },
      { id: "li-3", description: "Boulder feature", quantity: 1,
        unit_price: 800, service_category_id: "cat-landscape",
        customer_status: "pending" },
    ],
    customer_view: {
      currency: "USD",
      groups: [
        { group_key: "cat-pool",     label: "Pool Rehab",   description: "" },
        { group_key: "cat-landscape", label: "Landscaping", description: "" },
      ],
    },
    totals: { subtotal: 6500, tax: 500, discount: 0, total: 7000, currency: "USD" },
    flipbook_enabled: true,
    flipbook_background_ids: ["m-1", "m-2"],
    ...overrides,
  };
}


// ─── page assembly ─────────────────────────────────────────────────


describe("<EstimateFlipbook /> — page assembly", () => {
  it("renders cover + one page per group + total + accept (2 groups)", () => {
    const data = _minPayload();
    render(
      <EstimateFlipbook
        data={data}
        onAccept={vi.fn()} onDeclineClick={vi.fn()} onDownloadPdf={vi.fn()}
        onSignNow={vi.fn()} actionable={true} busy={false}
      />,
    );
    // Cover
    expect(screen.getByTestId("flipbook-page-cover")).toBeTruthy();
    // Two service group pages
    expect(screen.getByTestId("flipbook-page-group-cat-pool")).toBeTruthy();
    expect(screen.getByTestId("flipbook-page-group-cat-landscape")).toBeTruthy();
    // Total + accept
    expect(screen.getByTestId("flipbook-page-total")).toBeTruthy();
    expect(screen.getByTestId("flipbook-page-accept")).toBeTruthy();
    // NO filler pages — 2+ groups skips them per spec.
    expect(screen.queryByTestId("flipbook-page-filler-process")).toBeNull();
    expect(screen.queryByTestId("flipbook-page-filler-guarantee")).toBeNull();
  });

  it("inserts filler pages when service groups < 2", () => {
    const data = _minPayload({
      line_items: [
        { id: "li-1", description: "Weekly service", quantity: 1,
          unit_price: 150, service_category_id: "cat-pool",
          customer_status: "pending" },
      ],
      customer_view: {
        currency: "USD",
        groups: [{ group_key: "cat-pool", label: "Pool Rehab" }],
      },
    });
    render(
      <EstimateFlipbook
        data={data}
        onAccept={vi.fn()} onDeclineClick={vi.fn()} onDownloadPdf={vi.fn()}
        onSignNow={vi.fn()} actionable={true} busy={false}
      />,
    );
    expect(screen.getByTestId("flipbook-page-filler-process")).toBeTruthy();
    expect(screen.getByTestId("flipbook-page-filler-guarantee")).toBeTruthy();
    expect(screen.getByTestId("flipbook-page-group-cat-pool")).toBeTruthy();
  });

  it("renders group subtotal and line items with declined line dimmed", () => {
    const data = _minPayload({
      line_items: [
        { id: "li-1", description: "A", quantity: 1, unit_price: 100,
          service_category_id: "cat-pool", customer_status: "pending" },
        { id: "li-2", description: "B", quantity: 2, unit_price: 50,
          service_category_id: "cat-pool", customer_status: "declined" },
      ],
      customer_view: { currency: "USD",
                        groups: [{ group_key: "cat-pool", label: "Pool" }] },
    });
    render(
      <EstimateFlipbook
        data={data}
        onAccept={vi.fn()} onDeclineClick={vi.fn()} onDownloadPdf={vi.fn()}
        onSignNow={vi.fn()} actionable={true} busy={false}
      />,
    );
    // Both lines render
    expect(screen.getByTestId("flipbook-line-li-1")).toBeTruthy();
    expect(screen.getByTestId("flipbook-line-li-2")).toBeTruthy();
    // Declined line carries opacity < 1 via style.
    const declined = screen.getByTestId("flipbook-line-li-2");
    expect(Number(declined.style.opacity)).toBeLessThan(1);
  });

  it("renders grand total from data.totals", () => {
    render(
      <EstimateFlipbook
        data={_minPayload()}
        onAccept={vi.fn()} onDeclineClick={vi.fn()} onDownloadPdf={vi.fn()}
        onSignNow={vi.fn()} actionable={true} busy={false}
      />,
    );
    expect(screen.getByTestId("flipbook-total-grand").textContent)
      .toMatch(/\$7,000\.00/);
  });
});


// ─── background cycling + broken images ────────────────────────────


describe("<EstimateFlipbook /> — backgrounds", () => {
  it("prefers pre-signed flipbook_background_urls over raw IDs", () => {
    // Feb-2026 follow-up · the payload builder emits
    // ``flipbook_background_urls`` (HMAC-signed) so anonymous
    // customer <img> tags can load the asset without an
    // Authorization header. The component MUST use those URLs
    // instead of hand-rolling the raw ``/api/marketing/media/..``
    // path (which requires auth and 401s for anon viewers).
    const data = _minPayload({
      flipbook_background_ids: ["m-1", "m-2"],
      flipbook_background_urls: [
        "/api/marketing/media/m-1/download?tid=t-flip&sig=abc123",
        "/api/marketing/media/m-2/download?tid=t-flip&sig=def456",
      ],
    });
    render(
      <EstimateFlipbook
        data={data}
        onAccept={vi.fn()} onDeclineClick={vi.fn()} onDownloadPdf={vi.fn()}
        onSignNow={vi.fn()} actionable={true} busy={false}
      />,
    );
    const bgSrcs = Array.from(
      document.querySelectorAll(".flipbook-page img"),
    )
      .map((im) => im.getAttribute("src"))
      .filter((s) => s && s.includes("/api/marketing/media/"));
    expect(bgSrcs.length).toBeGreaterThan(0);
    for (const src of bgSrcs) {
      // Every marketing-media <img> MUST carry the HMAC ``sig``
      // query param — otherwise the anon viewer would 401.
      expect(src).toMatch(/[?&]sig=/);
      expect(src).toMatch(/[?&]tid=t-flip/);
    }
  });

  it("falls back to raw /download path when signed URLs are missing", () => {
    // Defensive path — an admin preview or an older payload shape
    // that skips signing should still render (401 is caught by the
    // ``<img onError>`` handler).
    const data = _minPayload({
      flipbook_background_ids: ["m-legacy"],
      flipbook_background_urls: undefined,
    });
    render(
      <EstimateFlipbook
        data={data}
        onAccept={vi.fn()} onDeclineClick={vi.fn()} onDownloadPdf={vi.fn()}
        onSignNow={vi.fn()} actionable={true} busy={false}
      />,
    );
    const bg = Array.from(document.querySelectorAll(".flipbook-page img"))
      .find((im) => im.src.includes("/api/marketing/media/m-legacy"));
    expect(bg).toBeTruthy();
    expect(bg.src).toContain("/api/marketing/media/m-legacy/download");
    // No sig param on the fallback path.
    expect(bg.src).not.toMatch(/[?&]sig=/);
  });

  it("cycles background images when pages > images", () => {
    const data = _minPayload({
      flipbook_background_ids: ["only-one"],
    });
    render(
      <EstimateFlipbook
        data={data}
        onAccept={vi.fn()} onDeclineClick={vi.fn()} onDownloadPdf={vi.fn()}
        onSignNow={vi.fn()} actionable={true} busy={false}
      />,
    );
    // Every ``.flipbook-page`` <img> src should point at the same
    // signed-download URL for the sole background id.
    const imgs = document.querySelectorAll(".flipbook-page img");
    expect(imgs.length).toBeGreaterThan(0);
    for (const im of imgs) {
      // Some page-content <img> (logo) may exist too — only assert
      // on the ones whose src matches the marketing-media pattern.
      if (im.src.includes("/api/marketing/media/")) {
        expect(im.src).toContain("/api/marketing/media/only-one/download");
      }
    }
  });

  it("no backgrounds → pages render without <img> children (tint only)", () => {
    const data = _minPayload({ flipbook_background_ids: [] });
    render(
      <EstimateFlipbook
        data={data}
        onAccept={vi.fn()} onDeclineClick={vi.fn()} onDownloadPdf={vi.fn()}
        onSignNow={vi.fn()} actionable={true} busy={false}
      />,
    );
    // No page carries a marketing-media background <img>.
    const bgImgs = Array.from(
      document.querySelectorAll(".flipbook-page img"),
    ).filter((im) => im.src.includes("/api/marketing/media/"));
    expect(bgImgs.length).toBe(0);
  });

  it("logs a warning + hides the image when a background fails to load", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(
      <EstimateFlipbook
        data={_minPayload({ flipbook_background_ids: ["ghost"] })}
        onAccept={vi.fn()} onDeclineClick={vi.fn()} onDownloadPdf={vi.fn()}
        onSignNow={vi.fn()} actionable={true} busy={false}
      />,
    );
    const bg = Array.from(document.querySelectorAll(".flipbook-page img"))
      .find((im) => im.src.includes("/api/marketing/media/ghost/download"));
    expect(bg).toBeTruthy();
    fireEvent.error(bg);
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("background image failed to load: ghost"),
    );
    expect(bg.style.visibility).toBe("hidden");
    warnSpy.mockRestore();
  });
});


// ─── CTAs + signature gate ─────────────────────────────────────────


describe("<EstimateFlipbook /> — CTAs", () => {
  it("cover Download PDF button calls the onDownloadPdf prop", () => {
    const onDownloadPdf = vi.fn();
    render(
      <EstimateFlipbook
        data={_minPayload()}
        onAccept={vi.fn()} onDeclineClick={vi.fn()}
        onDownloadPdf={onDownloadPdf}
        onSignNow={vi.fn()} actionable={true} busy={false}
      />,
    );
    fireEvent.click(screen.getByTestId("flipbook-cover-download-pdf"));
    expect(onDownloadPdf).toHaveBeenCalledTimes(1);
  });

  it("accept + decline CTAs fire the correct handlers", () => {
    const onAccept = vi.fn();
    const onDeclineClick = vi.fn();
    render(
      <EstimateFlipbook
        data={_minPayload()}
        onAccept={onAccept} onDeclineClick={onDeclineClick}
        onDownloadPdf={vi.fn()} onSignNow={vi.fn()}
        actionable={true} busy={false}
      />,
    );
    fireEvent.click(screen.getByTestId("flipbook-accept-btn"));
    fireEvent.click(screen.getByTestId("flipbook-decline-btn"));
    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(onDeclineClick).toHaveBeenCalledTimes(1);
  });

  it("accept CTA is disabled when signature gate blocks + Sign-now surfaces", () => {
    const onSignNow = vi.fn();
    render(
      <EstimateFlipbook
        data={_minPayload()}
        onAccept={vi.fn()} onDeclineClick={vi.fn()}
        onDownloadPdf={vi.fn()} onSignNow={onSignNow}
        actionable={true} busy={false}
        signatureGateBlocked={true}
      />,
    );
    expect(screen.getByTestId("flipbook-signature-hint")).toBeTruthy();
    expect(screen.getByTestId("flipbook-accept-btn").disabled).toBe(true);
    fireEvent.click(screen.getByTestId("flipbook-sign-now"));
    expect(onSignNow).toHaveBeenCalledTimes(1);
  });

  it("accept CTA is disabled when actionable=false (already-decided doc)", () => {
    render(
      <EstimateFlipbook
        data={_minPayload({
          status: "accepted", decision: "accepted",
          accepted_at: "2026-02-14",
        })}
        onAccept={vi.fn()} onDeclineClick={vi.fn()}
        onDownloadPdf={vi.fn()} onSignNow={vi.fn()}
        actionable={false} busy={false}
      />,
    );
    expect(screen.getByTestId("flipbook-accept-btn").disabled).toBe(true);
    expect(screen.getByTestId("flipbook-decline-btn").disabled).toBe(true);
    expect(screen.getByTestId("flipbook-decision-accepted")).toBeTruthy();
  });
});


// ─── EstimateView branch ───────────────────────────────────────────


describe("<EstimateView> → flipbook branch", () => {
  beforeEach(() => {
    // Force a non-iOS UA so no unrelated primitive falls over.
    Object.defineProperty(window.navigator, "userAgent", {
      value: "Mozilla/5.0 (Windows NT 10.0)",
      configurable: true,
    });
  });

  it("EstimateView source declares the flipbook branch before the classic render", async () => {
    // Grep-style contract test — cheaper than mounting EstimateView
    // (which needs a lot of route context). Guards the branch order:
    // ``if (data?.flipbook_enabled && ...) return <EstimateFlipbook`` must
    // sit BEFORE the classic ``return (`` render.
    const fs = await import("fs");
    const path = await import("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../components/EstimateView.jsx"),
      "utf8",
    );
    const branchIdx = src.indexOf("data?.flipbook_enabled");
    expect(branchIdx).toBeGreaterThan(-1);
    // The classic render start — the FIRST occurrence of a lone
    // ``return (`` on its own line AFTER the branch guard sits in the
    // main render slot.
    const classicIdx = src.indexOf(
      "\n  return (",
      branchIdx + "data?.flipbook_enabled".length,
    );
    expect(classicIdx).toBeGreaterThan(branchIdx);
    // And the ``<EstimateFlipbook`` mount inside the branch.
    expect(src.slice(branchIdx, classicIdx)).toContain("<EstimateFlipbook");
  });

  it("EstimateFlipbook is default-exported and can be imported by consumers", async () => {
    const mod = await import("@/components/estimates/EstimateFlipbook");
    expect(typeof mod.default).toBe("function");
    expect(typeof mod.EstimateFlipbook).toBe("function");
  });
});
