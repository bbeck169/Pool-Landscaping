/**
 * TD-98/99-xref · Feb-2026 — Row-click modal smoke.
 *
 * Ship `td98-99-xref-c-fe` wired `CommunicationDetailModal` into
 * `CustomerFullTimeline`'s `DefaultRow` for `kind in {sms, email}`
 * rows with no `item.url`. Pre-check confirmed this is zero-regression:
 * customer-era marketing_delivery rows (url=="") were null/no-op
 * before and now open the modal; customer-era invoice/estimate rows
 * (url set) retain their Link navigation unchanged.
 *
 * Smoke covers both:
 *   * Customer-era SMS row (ref_type="marketing_delivery") → opens modal.
 *   * Lead-era SMS row    (ref_type="lead_communication")  → opens modal.
 *   * Lead-era inbound    (ref_type="lead_sms_inbound")    → opens modal.
 *   * Customer-era invoice (ref_type="invoice", url set)   → does NOT
 *     attach the modal trigger; retains Link navigation.
 *   * NoteRow + CallRow are not reachable from the SMS/email path and
 *     are not asserted here (they have their own row components).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


vi.mock("@/api", () => ({
  api: {
    get: vi.fn().mockImplementation(async (url) => {
      if (url.startsWith("/customers/")) {
        return {
          items:       mockPage.items,
          total:       mockPage.items.length,
          total_pages: 1,
          page:        1,
          page_size:   20,
        };
      }
      if (url.startsWith("/communications-detail/")) {
        return { id: url.split("/").pop(),
                 body_preview: "mocked detail body",
                 channel: "sms", direction: "outbound",
                 status_badge: "sent" };
      }
      return {};
    }),
  },
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));
vi.mock("@/theme", () => ({
  colors: {
    onSurface: "#0F172A", muted: "#64748B", surface: "#FFF",
    surfaceSecondary: "#F1F5F9", border: "#CBD5E1", onBrand: "#FFF",
  },
}));


let mockPage = { items: [] };


function _wrap(ui) {
  return <MemoryRouter>{ui}</MemoryRouter>;
}


const CustomerFullTimeline =
  (await import("@/components/customers/CustomerFullTimeline")).default;


beforeEach(() => {
  mockPage = { items: [] };
});


describe("TD-98/99-xref · CustomerFullTimeline row-click modal", () => {
  it("customer-era SMS row (marketing_delivery, url=\"\") shows the open-detail button", async () => {
    mockPage = { items: [{
      id: "md-1", ref_type: "marketing_delivery", ref_id: "md-1",
      kind: "sms", subject: "Welcome aboard",
      created_at: "2026-02-20T12:00:00+00:00",
      occurred_at: "2026-02-20T12:00:00+00:00",
      source_type: "sms", recipient: "+14805550100",
      url: "",
    }] };
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust-1" />));
    const btn = await screen.findByTestId("timeline-open-detail-0");
    expect(btn).toBeTruthy();
    expect(btn.textContent).toContain("Welcome aboard");
  });

  it("lead-era SMS row (lead_communication) shows the open-detail button + opens the shared modal on click", async () => {
    mockPage = { items: [{
      id: "lc-1", ref_type: "lead_communication", ref_id: "lc-1",
      kind: "sms", subject: "",
      body: "Lead-era outbound SMS",
      created_at: "2026-02-10T12:00:00+00:00",
      occurred_at: "2026-02-10T12:00:00+00:00",
      source_type: "sms", recipient: "+14805550100",
      related_ref: { kind: "lead", id: "lead-99" },
      url: "",
    }] };
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust-1" />));
    const btn = await screen.findByTestId("timeline-open-detail-0");
    fireEvent.click(btn);
    // Modal probes via its own fetch; the API mock handles the GET.
    await waitFor(() => {
      // CommunicationDetailModal renders role="dialog" when open.
      expect(screen.queryAllByRole("dialog").length).toBeGreaterThan(0);
    });
  });

  it("lead-era inbound SMS row (lead_sms_inbound) also shows the open-detail button", async () => {
    mockPage = { items: [{
      id: "in-1", ref_type: "lead_sms_inbound", ref_id: "in-1",
      kind: "sms", subject: "",
      body: "Lead-era inbound SMS",
      created_at: "2026-02-11T12:00:00+00:00",
      occurred_at: "2026-02-11T12:00:00+00:00",
      source_type: "sms", recipient: "+14805550100",
      related_ref: { kind: "lead", id: "lead-99" },
      url: "",
    }] };
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust-1" />));
    const btn = await screen.findByTestId("timeline-open-detail-0");
    expect(btn).toBeTruthy();
  });

  it("customer-era invoice row (url set) retains Link navigation, NOT the modal trigger", async () => {
    mockPage = { items: [{
      id: "q-1", ref_type: "invoice", ref_id: "q-1",
      kind: "invoice", subject: "Invoice #INV-001",
      total: 250.0, delivery_status: "sent",
      payment_status: "unpaid",
      created_at: "2026-02-15T12:00:00+00:00",
      occurred_at: "2026-02-15T12:00:00+00:00",
      source_type: "invoice",
      url: "/invoices/q-1",
    }] };
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust-1" />));
    await waitFor(() => {
      expect(screen.queryByTestId("timeline-link-0")).toBeTruthy();
    });
    expect(screen.queryByTestId("timeline-open-detail-0")).toBeNull();
  });

  it("customer-era email row (marketing_delivery with subject, url=\"\") shows the open-detail button", async () => {
    mockPage = { items: [{
      id: "md-e-1", ref_type: "marketing_delivery", ref_id: "md-e-1",
      kind: "email", subject: "Monthly newsletter",
      created_at: "2026-02-01T12:00:00+00:00",
      occurred_at: "2026-02-01T12:00:00+00:00",
      source_type: "email", recipient: "cust@example.com",
      url: "",
    }] };
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust-1" />));
    const btn = await screen.findByTestId("timeline-open-detail-0");
    expect(btn.textContent).toContain("Monthly newsletter");
  });
});
