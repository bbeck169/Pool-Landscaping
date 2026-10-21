/**
 * TD-98-be-sources · Feb-2026 — CustomerFullTimeline delivery_error badge.
 *
 * Locks:
 *   1. Admin session sees the red "Error" badge when an item carries
 *      a top-level ``delivery_error`` field.
 *   2. Portal / customer session never renders the badge because the
 *      BE strips ``delivery_error`` at source — the FE conditional
 *      is a defense-in-depth (badge only renders when field present).
 *   3. Items without ``delivery_error`` don't render the badge
 *      regardless of role.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { getSpy, useAuthSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(), useAuthSpy: vi.fn(),
}));

vi.mock("@/api",   () => ({ api: { get: (...a) => getSpy(...a) } }));
vi.mock("@/auth",  () => ({ useAuth: () => useAuthSpy() }));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f8fafc", border: "#e5e7eb",
    onSurface: "#111827", muted: "#6b7280",
    brand: "#0284c7", onBrand: "#fff",
  },
}));


import CustomerFullTimeline
  from "@/components/customers/CustomerFullTimeline";


function _wrap(ui) { return <MemoryRouter>{ui}</MemoryRouter>; }


beforeEach(() => {
  getSpy.mockReset();
  useAuthSpy.mockReset();
});


const _DISPATCH_ERR_ITEM = {
  kind: "email",
  source_type: "email",
  subject: "Failed send",
  template_name: "",
  delivery_status: "failed",
  delivery_error: "twilio_error_30001",
  created_at: "2026-02-10T10:00:00+00:00",
  occurred_at: "2026-02-10T10:00:00+00:00",
  ref_type: "notification_dispatch",
  ref_id: "d-err-1",
  recipient: "c@ex.com",
  trigger_kind: "",
  related_ref: null,
  url: "",
  body: "Error body",
  summary: "Failed · failed",
  actor: null,
  id: "d-err-1",
};


const _CLEAN_ITEM = {
  kind: "email",
  source_type: "email",
  subject: "Clean send",
  template_name: "",
  delivery_status: "sent",
  created_at: "2026-02-11T10:00:00+00:00",
  occurred_at: "2026-02-11T10:00:00+00:00",
  ref_type: "notification_dispatch",
  ref_id: "d-ok-1",
  recipient: "c@ex.com",
  trigger_kind: "",
  related_ref: null,
  url: "",
  body: "Clean body",
  summary: "Clean · sent",
  actor: null,
  id: "d-ok-1",
};


describe("TD-98-be-sources · CustomerFullTimeline delivery_error badge", () => {
  it("admin: renders red Error badge when item carries delivery_error", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [_DISPATCH_ERR_ITEM],
      page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="c1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const badge = await screen.findByTestId("timeline-delivery-error-0");
    expect(badge).toBeTruthy();
    expect(badge.textContent.trim().toLowerCase()).toContain("error");
    // Full error text is in the title attr (hover tooltip for admins).
    expect(badge.getAttribute("title")).toBe("twilio_error_30001");
  });

  it("admin: no badge when delivery_error is absent (clean send)", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [_CLEAN_ITEM],
      page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="c1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(screen.queryByTestId("timeline-delivery-error-0")).toBeNull();
  });

  it("portal (customer role): BE strips delivery_error → no badge rendered", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "customer" } });
    // Portal response — BE already stripped delivery_error at source.
    const portalItem = { ..._DISPATCH_ERR_ITEM };
    delete portalItem.delivery_error;
    getSpy.mockResolvedValue({
      items: [portalItem],
      page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="portal" customerId="c1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(screen.queryByTestId("timeline-delivery-error-0")).toBeNull();
    // delivery_status chip should still render (portal visible).
    expect(screen.getByText("failed")).toBeTruthy();
  });
});
