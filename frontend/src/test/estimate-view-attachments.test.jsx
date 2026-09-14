/**
 * Feb-2026 · Public Quote Attachments — customer-facing
 * ``EstimateView`` Attachments section contract.
 *
 * Coverage:
 *   1. When ``data.attachments`` is a non-empty array, the
 *      Attachments section renders with:
 *        - the "Attachments" title
 *        - one row per attachment with the filename + human size
 *        - a Download button whose href = ``att.url`` and opens in
 *          a new tab (``target="_blank" rel="noopener"``)
 *        - stable testids ``estimate-attachment-row-<i>`` +
 *          ``estimate-attachment-download-<i>``.
 *   2. When ``data.attachments`` is missing or an empty array, the
 *      Attachments section is NOT emitted at all — the whole block
 *      is gated on ``length > 0`` so an empty list must not leak a
 *      stray heading.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const { getSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api_base: () => "http://localhost/api",
  api: {
    get: (...a) => getSpy(...a),
    post: vi.fn(),
    patch: (...a) => patchSpy(...a),
    del: vi.fn(),
  },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ id: "q-1" }),
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0B4A6F", muted: "#6B7280", onSurface: "#111827",
    border: "#E5E7EB", surface: "#FFFFFF",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

import EstimateView from "@/components/EstimateView";


function _basePayload() {
  return {
    status: "sent",
    decision: null,
    company: { name: "AquaTerra" },
    bill_to: { name: "Alice", customer_number: "C-42" },
    property_address: "123 Main St",
    header: {
      estimate_number: "EST-1001",
      estimate_date: "2026-02-14",
      customer_number: "C-42",
    },
    title: "Backyard makeover",
    line_items: [{ description: "Design", qty_hr: 1, visits: 1, total: 100 }],
    totals: {
      subtotal: 100, taxes: 8, amount_paid: 0,
      total_estimated_cost: 108,
      has_declined_lines: false, declined_line_count: 0,
    },
    notes: null,
    as_customer: true,
    customer_view: {
      customer_group_display: false,
      groups: [],
      subtotal: 100, tax: 8, discount: 0, total: 108,
      grouped_subtotal: 100, grouped_active_subtotal: 100,
      has_declined_groups: false, currency: "USD",
    },
  };
}


function _brandingResp() {
  return {
    tenant_id: "t-1",
    branding: {
      company_display_name: "AquaTerra",
      brand_primary_hex: "#0B4A6F",
    },
  };
}


function _setupRouting(payload) {
  getSpy.mockImplementation((path) => {
    if (typeof path === "string"
        && path.includes("/portal/tenant/branding")) {
      return Promise.resolve(_brandingResp());
    }
    if (typeof path === "string"
        && path.includes("/tenants/me/business-settings")) {
      return Promise.resolve({
        stored: _brandingResp().branding,
        effective: _brandingResp().branding,
      });
    }
    return Promise.resolve(payload);
  });
}


describe("EstimateView · Attachments section (public viewer)", () => {
  it("renders one row per attachment with the tokenised download URL", async () => {
    const payload = {
      ..._basePayload(),
      attachments: [
        {
          id: "file-1",
          filename: "site-plan.pdf",
          content_type: "application/pdf",
          size: 1_500_000,
          url: "https://app.example.com/api/portal/quotes/via-token/files/file-1?token=jwt-abc",
        },
        {
          id: "file-2",
          filename: "before.jpg",
          content_type: "image/jpeg",
          size: 234_567,
          url: "https://app.example.com/api/portal/quotes/via-token/files/file-2?token=jwt-abc",
        },
      ],
    };
    _setupRouting(payload);
    render(<EstimateView estimateId="q-1" token="jwt-abc" />);

    // Section container appears (guards against a regression that
    // renders only rows but not the wrapping block).
    expect(await screen.findByTestId("estimate-attachments-section")).toBeTruthy();
    // "Attachments" heading is present exactly once inside the
    // section (not two, which would signal a duplicate render).
    const section = screen.getByTestId("estimate-attachments-section");
    expect(section.textContent).toMatch(/Attachments/);

    // Per-row + per-download testids resolve, and the href on each
    // Download button matches the exact URL supplied by the backend.
    const row0 = screen.getByTestId("estimate-attachment-row-0");
    const row1 = screen.getByTestId("estimate-attachment-row-1");
    expect(row0.textContent).toMatch(/site-plan\.pdf/);
    expect(row0.textContent).toMatch(/1\.4 MB/);
    expect(row1.textContent).toMatch(/before\.jpg/);
    expect(row1.textContent).toMatch(/229\.1 KB/);

    const dl0 = screen.getByTestId("estimate-attachment-download-0");
    const dl1 = screen.getByTestId("estimate-attachment-download-1");
    expect(dl0.getAttribute("href")).toBe(payload.attachments[0].url);
    expect(dl1.getAttribute("href")).toBe(payload.attachments[1].url);
    expect(dl0.getAttribute("target")).toBe("_blank");
    expect(dl0.getAttribute("rel")).toMatch(/noopener/);
  });

  it("hides the section entirely when attachments is empty or missing", async () => {
    // Empty array.
    _setupRouting({ ..._basePayload(), attachments: [] });
    const { unmount } = render(<EstimateView estimateId="q-1" token="jwt-a" />);
    // Wait for the viewer payload to be applied (a stable, always-
    // present testid) then assert the section is absent.
    await screen.findByTestId("estimate-view");
    expect(screen.queryByTestId("estimate-attachments-section")).toBeNull();
    expect(screen.queryByTestId("estimate-attachment-row-0")).toBeNull();
    unmount();

    // Missing key entirely — same guarantee.
    _setupRouting(_basePayload());
    render(<EstimateView estimateId="q-1" token="jwt-b" />);
    await screen.findByTestId("estimate-view");
    expect(screen.queryByTestId("estimate-attachments-section")).toBeNull();
  });

  // Feb-2026 · Attachment thumbnails — content-type branch coverage.
  // Image attachments render an <img> preview inside the tokenised
  // new-tab anchor; PDF attachments render an icon glyph (no <img>).
  it("renders an <img> thumbnail for image attachments in a new-tab anchor", async () => {
    const payload = {
      ..._basePayload(),
      attachments: [
        {
          id: "file-img",
          filename: "before.png",
          content_type: "image/png",
          size: 12_345,
          url: "https://app.example.com/api/portal/quotes/via-token/files/file-img?token=jwt-img",
        },
      ],
    };
    _setupRouting(payload);
    render(<EstimateView estimateId="q-1" token="jwt-img" />);

    const thumb = await screen.findByTestId("estimate-attachment-thumb-0");
    // The wrapping element is the <a target="_blank"> so clicking the
    // preview opens the tokenised URL in a new tab (same behaviour as
    // the Download button next to it).
    expect(thumb.tagName).toBe("A");
    expect(thumb.getAttribute("href")).toBe(payload.attachments[0].url);
    expect(thumb.getAttribute("target")).toBe("_blank");
    expect(thumb.getAttribute("rel")).toMatch(/noopener/);

    // The image-branch renders an <img> with the same tokenised URL as
    // src + lazy-loading + object-cover for the 64px square.
    const img = thumb.querySelector("img");
    expect(img).toBeTruthy();
    expect(img.getAttribute("src")).toBe(payload.attachments[0].url);
    expect(img.getAttribute("loading")).toBe("lazy");
    // No stray icon svgs when we're on the image branch.
    expect(thumb.querySelector("svg")).toBeNull();
  });

  it("renders a PDF icon (no <img>) for PDF attachments", async () => {
    const payload = {
      ..._basePayload(),
      attachments: [
        {
          id: "file-pdf",
          filename: "proposal.pdf",
          content_type: "application/pdf",
          size: 98_765,
          url: "https://app.example.com/api/portal/quotes/via-token/files/file-pdf?token=jwt-pdf",
        },
      ],
    };
    _setupRouting(payload);
    render(<EstimateView estimateId="q-1" token="jwt-pdf" />);

    const thumb = await screen.findByTestId("estimate-attachment-thumb-0");
    expect(thumb.tagName).toBe("A");
    expect(thumb.getAttribute("href")).toBe(payload.attachments[0].url);
    expect(thumb.getAttribute("target")).toBe("_blank");
    // PDF branch does NOT render an <img> element — that would 404 the
    // preview and paint a broken-image glyph. It renders a lucide
    // <svg> icon inside the 64px tile instead.
    expect(thumb.querySelector("img")).toBeNull();
    expect(thumb.querySelector("svg")).toBeTruthy();
  });
});
