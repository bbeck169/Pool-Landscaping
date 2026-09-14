/**
 * Feb-2026 · CustomerFullTimeline — filter chips, pagination row,
 * and both admin + portal scope endpoints.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: { get: (...a) => getSpy(...a) },
}));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f8fafc", border: "#e5e7eb",
    borderStrong: "#d1d5db", onSurface: "#111827", muted: "#6b7280",
    brand: "#0284c7", onBrand: "#fff",
  },
}));

import CustomerFullTimeline
  from "@/components/customers/CustomerFullTimeline";


function _mkItem(overrides = {}) {
  return {
    kind: "email",
    subject: "Your invoice is ready",
    template_name: "invoice_sent",
    delivery_status: "sent",
    created_at: "2026-02-14T10:00:00Z",
    ref_type: "marketing_delivery",
    ref_id: "md_1",
    url: "",
    recipient: "customer@example.com",
    total: 0,
    ...overrides,
  };
}


function _wrap(ui) {
  return <MemoryRouter>{ui}</MemoryRouter>;
}


beforeEach(() => {
  getSpy.mockReset();
});


describe("CustomerFullTimeline · admin scope", () => {
  it("fetches /customers/{id}/timeline with paginated query params", async () => {
    getSpy.mockResolvedValue({
      items: [_mkItem()], page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const path = getSpy.mock.calls[0][0];
    expect(path).toMatch(/^\/customers\/cust_1\/timeline\?/);
    expect(path).toMatch(/page=1/);
    expect(path).toMatch(/page_size=20/);
    // No ``kind`` query when the "all" chip is active.
    expect(path).not.toMatch(/kind=/);
  });

  it("filter chip re-fires the request with ``kind`` CSV", async () => {
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    // Click "Invoice" — expect the next call to carry ``kind=invoice``.
    fireEvent.click(screen.getByTestId("timeline-filter-invoice"));
    await waitFor(() => expect(getSpy.mock.calls.length).toBeGreaterThan(1));
    const path = getSpy.mock.calls[getSpy.mock.calls.length - 1][0];
    expect(path).toMatch(/kind=invoice/);
  });

  it("renders all four filter chip testids + row + link + pagination", async () => {
    getSpy.mockResolvedValue({
      items: [
        _mkItem({ kind: "invoice", subject: "Invoice #42",
                     ref_type: "invoice", ref_id: "inv_42",
                     url: "/invoices/inv_42", total: 120 }),
        _mkItem({ kind: "sms", subject: "Reminder: your service tomorrow",
                     ref_id: "md_2", created_at: "2026-02-13T09:00:00Z",
                     recipient: "+15555550100" }),
      ],
      page: 1, page_size: 20, total: 2, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    // Chips.
    for (const k of ["all", "email", "sms", "invoice", "estimate"]) {
      expect(screen.getByTestId(`timeline-filter-${k}`)).toBeTruthy();
    }
    // Rows.
    expect(await screen.findByTestId("timeline-row-0")).toBeTruthy();
    expect(screen.getByTestId("timeline-row-1")).toBeTruthy();
    // Invoice link (admin viewer path).
    const link = screen.getByTestId("timeline-link-0");
    expect(link.getAttribute("href")).toBe("/invoices/inv_42");
    // Pagination — always mounted (Feb-2026 mobile-testable contract).
    expect(screen.getByTestId("timeline-pagination")).toBeTruthy();
    expect(screen.getByTestId("timeline-pagination-prev").disabled).toBe(true);
    expect(screen.getByTestId("timeline-pagination-next").disabled).toBe(true);
    expect(screen.getByTestId("timeline-page-indicator").textContent)
      .toMatch(/Page 1 of 1.*2 total/);
  });

  it("pagination next button advances the page on multi-page results", async () => {
    getSpy.mockResolvedValue({
      items: [_mkItem()], page: 1, page_size: 1, total: 5, total_pages: 5,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const nextBtn = screen.getByTestId("timeline-pagination-next");
    expect(nextBtn.disabled).toBe(false);
    fireEvent.click(nextBtn);
    await waitFor(() => expect(getSpy.mock.calls.length).toBeGreaterThan(1));
    const path = getSpy.mock.calls[getSpy.mock.calls.length - 1][0];
    expect(path).toMatch(/page=2/);
  });
});


describe("CustomerFullTimeline · portal scope", () => {
  it("fetches /customers/me/timeline (no customerId prop needed)", async () => {
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="portal" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const path = getSpy.mock.calls[0][0];
    expect(path).toMatch(/^\/customers\/me\/timeline\?/);
  });

  it("invoice link points at the portal viewer path", async () => {
    getSpy.mockResolvedValue({
      items: [_mkItem({ kind: "invoice", subject: "Invoice #99",
                          ref_type: "invoice", ref_id: "inv_99",
                          url: "/portal/invoices/inv_99", total: 42 })],
      page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="portal" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const link = await screen.findByTestId("timeline-link-0");
    expect(link.getAttribute("href")).toBe("/portal/invoices/inv_99");
  });
});
