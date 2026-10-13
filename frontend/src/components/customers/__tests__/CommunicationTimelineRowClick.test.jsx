/**
 * P2 #5 · Feb-2026 — CommunicationTimeline row click vitest.
 *
 * Locks three invariants on the I7 Wave A customer-detail timeline:
 *   1. Row renders a "View details" button when variant="admin"
 *      AND item.id is present.
 *   2. Click opens the shared Dialog modal with the correct rowId
 *      (verified by inspecting the mock-captured fetch URL).
 *   3. Portal variant (variant="portal") does NOT render the
 *      View-details button — read-only on the customer surface.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup }
  from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { apiGetSpy } = vi.hoisted(() => ({ apiGetSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGetSpy(...a),
    post: vi.fn(),
  },
}));


import CommunicationTimeline
  from "@/components/customers/CommunicationTimeline";


const TIMELINE_PAGE = {
  items: [
    {
      id: "row-sms-1", type: "sms",
      occurred_at: "2026-02-15T13:00:00+00:00",
      actor_label: "System",
      body_preview: "Thanks for the message!",
      recipient: "+14805550001",
      delivery_status: "sent",
    },
    {
      id: "row-email-2", type: "email",
      occurred_at: "2026-02-15T14:00:00+00:00",
      actor_label: "Admin",
      subject: "Your quote",
      body_preview: "Hi Carla, your quote is ready.",
      recipient: "carla@example.com",
      delivery_status: "delivered",
    },
  ],
  has_more: false,
  next_before: null,
};


beforeEach(() => {
  apiGetSpy.mockReset();
  apiGetSpy.mockImplementation((url) => {
    if (url.includes("/communication-timeline")) {
      return Promise.resolve(TIMELINE_PAGE);
    }
    if (url.startsWith("/communications-detail/")) {
      return Promise.resolve({
        source: "marketing_deliveries",
        channel: "email",
        direction: "outbound",
        subject: "Your quote",
        body_available: true,
        body: "<p>Hi Carla</p>",
        body_format: "html",
      });
    }
    return Promise.resolve(null);
  });
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });


function _mount(variant = "admin") {
  return render(
    <MemoryRouter>
      <CommunicationTimeline customerId="cust-1" variant={variant} />
    </MemoryRouter>,
  );
}


describe("CommunicationTimeline · row click → shared Dialog modal", () => {
  it("renders View details button on each admin row with an id", async () => {
    _mount("admin");
    await waitFor(() => {
      expect(screen.queryByTestId("timeline-view-detail-row-sms-1"))
        .toBeTruthy();
      expect(screen.queryByTestId("timeline-view-detail-row-email-2"))
        .toBeTruthy();
    });
  });

  it("click fires the detail fetch with the correct rowId", async () => {
    _mount("admin");
    const btn = await screen.findByTestId("timeline-view-detail-row-email-2");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(apiGetSpy).toHaveBeenCalledWith("/communications-detail/row-email-2");
    });
    // Modal mounted + body present.
    await screen.findByTestId("comm-detail-modal");
  });

  it("portal variant hides the View details affordance", async () => {
    _mount("portal");
    await waitFor(() => {
      expect(screen.queryByTestId("communication-timeline-portal"))
        .toBeTruthy();
    });
    expect(screen.queryByTestId("timeline-view-detail-row-sms-1"))
      .toBeNull();
    expect(screen.queryByTestId("timeline-view-detail-row-email-2"))
      .toBeNull();
  });
});
