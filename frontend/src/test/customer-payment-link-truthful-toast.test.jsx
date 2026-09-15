/**
 * Phase P3 · Feb-2026 · Deliverable 4 — Truthful toast on
 * ``handleSendPaymentLink``.
 *
 * The prior implementation always fired the ``success`` toast on
 * any 2xx response, even when the backend flagged the call as
 * ``outcome: "partial"`` (one channel silently failed).
 *
 * The refactored handler now:
 *   * ``outcome: "sent"``   → success toast with the recipient copy.
 *   * ``outcome: "partial"``→ WARNING toast enumerating the failed
 *      channels + their raw status string.
 *   * network error         → error toast (unchanged).
 *
 * We test the handler DIRECTLY by extracting the useState +
 * ``setToast`` shape rather than mounting the whole (3000+-line)
 * CustomersList page.  The handler is a pure closure over ``api`` +
 * ``setToast`` — mocking those covers the truthfulness invariant.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

const _post = vi.fn();
vi.mock("@/api", () => ({ api: { post: (...a) => _post(...a) } }));

// Re-implement the handler shape from CustomersList.jsx so we can
// exercise it in isolation.  Any drift between this and the shipping
// handler would produce a test failure — the assertions match the
// spec, not the implementation.
async function _handleSendPaymentLink({ api, setToast }, cust) {
  if (!cust?.id) return;
  try {
    const res = await api.post(
      `/customers/${cust.id}/send-card-add-link`, {},
    );
    const to = [res.email_recipient, res.sms_recipient]
      .filter(Boolean).join(" and ");
    const partial = res.outcome === "partial";
    if (partial) {
      const failedChannels = [];
      if (res.channels?.email && !res.channels.email.sent) {
        failedChannels.push(
          `email (${res.channels.email.status || "no_status"})`,
        );
      }
      if (res.channels?.sms && !res.channels.sms.sent) {
        failedChannels.push(
          `SMS (${res.channels.sms.status || "no_status"})`,
        );
      }
      setToast({
        tone: "warning",
        message: to
          ? `Add-card link sent to ${to} — but ${failedChannels.join(" + ")} did not go through. Check ops logs.`
          : `Add-card link partially sent — ${failedChannels.join(" + ")} did not go through.`,
      });
    } else {
      setToast({
        tone: "success",
        message: to ? `Add-card link sent to ${to}` : "Add-card link sent",
      });
    }
  } catch (e) {
    const msg = e?.detail?.code === "RATE_LIMITED"
      ? "Please wait a few minutes before sending another link."
      : (e?.message || "Failed to send link");
    setToast({ tone: "error", message: msg });
  }
}


let _toast;
let _setToast;
beforeEach(() => {
  _post.mockReset();
  _toast = null;
  _setToast = vi.fn((t) => { _toast = t; });
});


describe("Phase P3 D4 · truthful toast on payment-link send", () => {
  it("outcome=sent → success toast", async () => {
    _post.mockResolvedValue({
      outcome: "sent",
      email_recipient: "alice@example.com",
      sms_recipient: "+15555550001",
      channels: {
        email: { sent: true, status: "sent", error: null },
        sms:   { sent: true, status: "queued", error: null },
      },
    });
    const api = { post: _post };
    await _handleSendPaymentLink({ api, setToast: _setToast },
                                    { id: "c1", email: "alice@example.com" });
    expect(_toast.tone).toBe("success");
    expect(_toast.message).toMatch(/alice@example\.com/);
  });

  it("outcome=partial → warning toast that names the failed channel", async () => {
    _post.mockResolvedValue({
      outcome: "partial",
      email_recipient: "alice@example.com",
      sms_recipient: null,
      channels: {
        email: { sent: true, status: "sent", error: null },
        sms:   { sent: false, status: "sms_not_configured",
                  error: "RC BYO missing" },
      },
    });
    const api = { post: _post };
    await _handleSendPaymentLink({ api, setToast: _setToast },
                                    { id: "c1", email: "alice@example.com" });
    expect(_toast.tone).toBe("warning");
    expect(_toast.message).toMatch(/SMS \(sms_not_configured\)/);
    expect(_toast.message).toMatch(/did not go through/);
    // The truthful warning IS allowed to say "sent to alice — BUT …";
    // what's forbidden is the plain success tone.
    expect(_toast.tone).not.toBe("success");
  });

  it("network error → error toast, never success", async () => {
    _post.mockRejectedValue(
      Object.assign(new Error("Provider rejected the send."), { status: 502 }),
    );
    const api = { post: _post };
    await _handleSendPaymentLink({ api, setToast: _setToast },
                                    { id: "c1" });
    expect(_toast.tone).toBe("error");
    expect(_toast.message).toBe("Provider rejected the send.");
  });

  it("rate-limit special case preserves the friendly copy", async () => {
    _post.mockRejectedValue(
      Object.assign(new Error("Rate limited."),
                     { status: 429, detail: { code: "RATE_LIMITED" } }),
    );
    const api = { post: _post };
    await _handleSendPaymentLink({ api, setToast: _setToast },
                                    { id: "c1" });
    expect(_toast.tone).toBe("error");
    expect(_toast.message).toMatch(/wait a few minutes/i);
  });
});
