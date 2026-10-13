/**
 * P2 #5 · Feb-2026 — CommunicationDetailModal vitest.
 *
 * Locks five invariants on the shared Dialog modal:
 *   1. Opens → fetches GET /communications-detail/<rowId> once.
 *   2. Email body renders inside <iframe srcDoc> with sandbox=""
 *      (no "allow-scripts" so <script> cannot execute).
 *   3. SMS / plaintext body renders inside the pre element,
 *      preserving line breaks.
 *   4. body_available: false → approved fallback copy renders and
 *      no iframe/pre element is mounted.
 *   5. Backend 404 → operator-friendly error copy renders.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";


const { apiGetSpy } = vi.hoisted(() => ({ apiGetSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGetSpy(...a),
    post: vi.fn(),
  },
}));


import CommunicationDetailModal, { BODY_NOT_STORED_COPY }
  from "@/components/communications/CommunicationDetailModal";


function _mount({ open = true, rowId = "md-1" } = {}) {
  return render(
    <CommunicationDetailModal
      open={open}
      rowId={rowId}
      onClose={() => {}}
    />,
  );
}


beforeEach(() => { apiGetSpy.mockReset(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });


describe("CommunicationDetailModal", () => {
  it("fetches detail endpoint once on open and renders email body in sandboxed iframe without allow-scripts", async () => {
    apiGetSpy.mockResolvedValue({
      source: "marketing_deliveries",
      channel: "email",
      direction: "outbound",
      subject: "Welcome aboard",
      from: null,
      to: "carla@example.com",
      cc: [], bcc: [],
      sent_at: "2026-02-15T12:00:00+00:00",
      delivered_at: "2026-02-15T12:01:00+00:00",
      opened_at: null, clicked_at: null, bounced_at: null,
      provider: "resend",
      provider_response_id: "re-abc-123",
      delivery_status: "delivered",
      body_available: true,
      body: "<p>Hi <b>Carla</b></p><script>window.oops=1</script>",
      body_format: "html",
    });
    _mount({ rowId: "md-1" });
    await waitFor(() => {
      expect(apiGetSpy).toHaveBeenCalledWith("/communications-detail/md-1");
    });
    const iframe = await screen.findByTestId("comm-detail-body-iframe");
    expect(iframe.tagName).toBe("IFRAME");
    // sandbox="" with no allow-scripts token — key security lock.
    const sandbox = iframe.getAttribute("sandbox");
    expect(sandbox).toBe("");
    expect(sandbox).not.toMatch(/allow-scripts/);
    // Body landed as srcDoc (host document; iframe won't actually
    // execute the <script> under sandbox="").
    expect(iframe.getAttribute("srcdoc") || iframe.srcdoc)
      .toContain("<p>Hi <b>Carla</b></p>");
    // Title still reflects subject.
    expect(screen.getByTestId("comm-detail-title").textContent)
      .toContain("Welcome aboard");
    // Meta line shows channel + provider.
    expect(screen.getByTestId("comm-detail-meta").textContent)
      .toContain("EMAIL");
    expect(screen.getByTestId("comm-detail-meta").textContent)
      .toContain("resend");
  });

  it("renders SMS body in a <pre> element preserving whitespace", async () => {
    apiGetSpy.mockResolvedValue({
      source: "lead_communications",
      channel: "sms",
      direction: "outbound",
      subject: "",
      from: "+16028874400",
      to: "+14805550001",
      cc: [], bcc: [],
      sent_at: "2026-02-15T13:00:00+00:00",
      delivery_status: "sent",
      body_available: true,
      body: "Line one.\nLine two.",
      body_format: "text",
    });
    _mount({ rowId: "lc-2" });
    const pre = await screen.findByTestId("comm-detail-body-text");
    expect(pre.tagName).toBe("PRE");
    expect(pre.textContent).toContain("Line one.");
    expect(pre.textContent).toContain("Line two.");
    // No iframe mounted for SMS.
    expect(screen.queryByTestId("comm-detail-body-iframe")).toBeNull();
  });

  it("renders the approved fallback copy when body_available is false", async () => {
    apiGetSpy.mockResolvedValue({
      source: "notification_dispatch_log",
      channel: "email",
      direction: "outbound",
      subject: "Your quote is ready",
      to: "customer@example.com",
      body_available: false,
      body: "",
      body_format: "html",
      delivery_status: "sent",
    });
    _mount({ rowId: "ndl-3" });
    const el = await screen.findByTestId("comm-detail-body-missing");
    expect(el.textContent).toContain(BODY_NOT_STORED_COPY);
    expect(BODY_NOT_STORED_COPY)
      .toContain("Message body was not stored on this record");
    // Neither iframe nor pre renders in this state.
    expect(screen.queryByTestId("comm-detail-body-iframe")).toBeNull();
    expect(screen.queryByTestId("comm-detail-body-text")).toBeNull();
  });

  it("renders operator-friendly error copy on 404 from the detail endpoint", async () => {
    apiGetSpy.mockRejectedValue({ status: 404, message: "Not found" });
    _mount({ rowId: "gone-1" });
    const err = await screen.findByTestId("comm-detail-error");
    expect(err.textContent).toContain("no longer available");
  });

  it("re-fetches when the rowId changes", async () => {
    apiGetSpy.mockImplementation((url) => Promise.resolve({
      source: "marketing_deliveries",
      channel: "email", direction: "outbound",
      subject: `subj:${url}`,
      body_available: true, body: "<p>b</p>", body_format: "html",
    }));
    const { rerender } = render(
      <CommunicationDetailModal open={true} rowId="first"
                                   onClose={() => {}} />,
    );
    await waitFor(() => {
      expect(apiGetSpy).toHaveBeenCalledWith("/communications-detail/first");
    });
    rerender(
      <CommunicationDetailModal open={true} rowId="second"
                                   onClose={() => {}} />,
    );
    await waitFor(() => {
      expect(apiGetSpy).toHaveBeenCalledWith("/communications-detail/second");
    });
    expect(apiGetSpy).toHaveBeenCalledTimes(2);
  });
});
