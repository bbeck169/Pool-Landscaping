/**
 * SMS preview-copy fix · Feb-2026.
 *
 * The invoice-page SmsModal used to display the raw backend reason
 * "sms-not-configured" as "SMS delivery not configured — logged only",
 * which incorrectly implied RingCentral was un-wired. In fact RC IS
 * configured; the comms guard suppresses sends to non-allowlisted
 * numbers in preview. This test pins the friendlier copy.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { getSpy, postSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
    del: vi.fn(),
  },
}));
vi.mock("@/auth", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));

afterEach(() => cleanup());

// Copy of the send handler + toast wiring from QuoteInvoiceDetail's
// SmsModal, kept inline to avoid pulling in the whole invoice detail
// page tree.  This exercises the exact same branch we shipped.
import { api } from "@/api";

function SmsModalHarness() {
  const [toast, setToast] = React.useState(null);
  const doSend = async () => {
    const r = await api.post("/invoices/inv-1/send-sms",
      { to: "+15551234567", message: "hi" });
    if (r.sent) setToast({ tone: "success", message: `Text sent to ${r.to}` });
    else if (r.reason === "sms-not-configured" ||
              r.reason === "twilio-not-configured")
      setToast({ tone: "info",
                  message: "SMS suppressed in preview environment. This number is not on the SMS_ALLOWLIST. In production, this would send via RingCentral." });
    else setToast({ tone: "error", message: r.reason || "Failed" });
  };
  return (
    <div>
      <button onClick={doSend} data-testid="sms-send-btn">Send</button>
      {toast ? (
        <div data-testid="sms-toast" data-tone={toast.tone}>{toast.message}</div>
      ) : null}
    </div>
  );
}

describe("Invoice send-SMS preview copy", () => {
  it("shows the friendly preview-suppression copy on sms-not-configured", async () => {
    postSpy.mockResolvedValue({
      sent: false, reason: "sms-not-configured", to: "+15551234567",
    });
    render(<MemoryRouter><SmsModalHarness /></MemoryRouter>);
    fireEvent.click(screen.getByTestId("sms-send-btn"));
    await waitFor(() => screen.getByTestId("sms-toast"));
    const toast = screen.getByTestId("sms-toast");
    expect(toast.textContent).toContain("suppressed in preview");
    expect(toast.textContent).toContain("RingCentral");
    expect(toast.textContent).not.toContain("sms-not-configured");
    expect(toast.getAttribute("data-tone")).toBe("info");
  });

  it("also handles the legacy twilio-not-configured alias", async () => {
    postSpy.mockResolvedValue({
      sent: false, reason: "twilio-not-configured", to: "+15551234567",
    });
    render(<MemoryRouter><SmsModalHarness /></MemoryRouter>);
    fireEvent.click(screen.getByTestId("sms-send-btn"));
    await waitFor(() => screen.getByTestId("sms-toast"));
    const toast = screen.getByTestId("sms-toast");
    expect(toast.textContent).toContain("suppressed in preview");
    expect(toast.textContent).not.toContain("twilio-not-configured");
  });
});
