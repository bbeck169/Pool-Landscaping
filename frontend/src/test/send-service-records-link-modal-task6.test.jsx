/**
 * Task 6 · Feb 2026 — SendServiceRecordsLinkModal regression tests.
 *
 * Covers:
 *  1. Modal renders with the correct heading + copy on open.
 *  2. Happy path: pick Email, hit Send, backend URL surfaces in the
 *     read-only "Link ready" panel and Copy button toggles state.
 *  3. Rate-limit 429 renders the throttle banner + disables Send.
 *  4. Consent-blocked customer hard-disables the matching tab and
 *     shows the tooltip banner. Send button also disabled.
 *  5. Muted customer disables BOTH tabs.
 *  6. Non-primary recipient override travels through to the payload.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

// Hoisted API mock — both api.get (status probe) and api.post (send)
// go through the same fake.
const { postSpy, getSpy } = vi.hoisted(() => ({
  postSpy: vi.fn(),
  getSpy: vi.fn(),
}));
vi.mock("@/api", () => ({
  api: {
    post: (...a) => postSpy(...a),
    get: (...a) => getSpy(...a),
  },
}));

import SendServiceRecordsLinkModal from "@/components/customers/SendServiceRecordsLinkModal";

const _origClipboard = navigator.clipboard;

function baseCustomer(overrides = {}) {
  return {
    id: "cust-1",
    name: "Jane Doe",
    email: "jane@example.com",
    emails: [{ address: "jane@example.com", is_primary: true }],
    mobiles: [{ number_e164: "+15555550100", is_primary: true }],
    channel_opt_in: { email_marketing: true, sms_marketing: true },
    is_muted: false,
    ...overrides,
  };
}

describe("SendServiceRecordsLinkModal", () => {
  beforeEach(() => {
    postSpy.mockReset();
    getSpy.mockReset();
    // Default status probe = 0/5 sends, not throttled.
    getSpy.mockResolvedValue({
      sends_last_hour: 0,
      rate_limit: 5,
      rate_limited: false,
      last_send_at: null,
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });
  afterEach(() => {
    cleanup();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: _origClipboard,
    });
  });

  it("renders the modal and prefills the email recipient", async () => {
    render(
      <SendServiceRecordsLinkModal
        open
        customer={baseCustomer()}
        onClose={() => {}}
        onSent={() => {}}
        onError={() => {}}
      />,
    );
    expect(await screen.findByTestId("sr-link-modal")).toBeTruthy();
    expect(screen.getByText(/Send service records link/i)).toBeTruthy();
    const recipient = screen.getByTestId("sr-link-recipient");
    expect(recipient.value).toBe("jane@example.com");
    // Both tabs enabled — no banners.
    expect(screen.queryByTestId("sr-link-consent-banner")).toBeNull();
    expect(screen.queryByTestId("sr-link-rate-banner")).toBeNull();
  });

  it("happy path: sends via email and surfaces the URL", async () => {
    const url = "https://portal.example/api/portal/auto-login?t=abc&redirect=/portal/service-reports";
    postSpy.mockResolvedValueOnce({
      ok: true,
      url,
      recipient: "jane@example.com",
      channel: "email",
      ttl_hours: 168,
      expires_at: "2026-02-14T12:00:00+00:00",
    });
    const onSent = vi.fn();
    render(
      <SendServiceRecordsLinkModal
        open
        customer={baseCustomer()}
        onClose={() => {}}
        onSent={onSent}
        onError={() => {}}
      />,
    );
    fireEvent.click(await screen.findByTestId("sr-link-send"));
    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    expect(postSpy).toHaveBeenCalledWith(
      "/customers/cust-1/send-service-records-link",
      { channel: "email", recipient: "jane@example.com" },
    );
    // Result panel renders the URL + expiry.
    expect(await screen.findByTestId("sr-link-result")).toBeTruthy();
    expect(screen.getByTestId("sr-link-result-url").value).toBe(url);
    expect(screen.getByTestId("sr-link-result-recipient").textContent)
      .toBe("jane@example.com");

    // Copy button toggles state.
    fireEvent.click(screen.getByTestId("sr-link-copy"));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(url),
    );
    expect(screen.getByTestId("sr-link-copy").textContent).toMatch(/Copied/);
  });

  it("renders the throttle banner and disables Send on 429", async () => {
    const err = new Error("Rate limit hit");
    err.status = 429;
    err.data = {
      detail: {
        detail: "rate_limited",
        limit_per_hour: 5,
        retry_after_seconds: 1800,
      },
    };
    postSpy.mockRejectedValueOnce(err);
    render(
      <SendServiceRecordsLinkModal
        open
        customer={baseCustomer()}
        onClose={() => {}}
        onSent={() => {}}
        onError={() => {}}
      />,
    );
    fireEvent.click(await screen.findByTestId("sr-link-send"));
    expect(await screen.findByTestId("sr-link-rate-banner")).toBeTruthy();
    // Send button now disabled.
    expect(screen.getByTestId("sr-link-send").disabled).toBe(true);
  });

  it("disables the email tab + shows a consent banner when email_marketing=false", async () => {
    render(
      <SendServiceRecordsLinkModal
        open
        customer={baseCustomer({
          channel_opt_in: { email_marketing: false, sms_marketing: true },
        })}
        onClose={() => {}}
        onSent={() => {}}
        onError={() => {}}
      />,
    );
    // Auto-switches to SMS since email is blocked.
    const smsTab = await screen.findByTestId("sr-link-tab-sms");
    await waitFor(() =>
      expect(smsTab.getAttribute("data-active")).toBe("true"),
    );
    const emailTab = screen.getByTestId("sr-link-tab-email");
    expect(emailTab.getAttribute("data-disabled")).toBe("true");
    expect(emailTab.disabled).toBe(true);
    expect(emailTab.getAttribute("title")).toMatch(/opt-in is off/i);
    // Recipient now the mobile number.
    expect(screen.getByTestId("sr-link-recipient").value).toBe("+15555550100");
  });

  it("disables BOTH tabs when the customer is muted", async () => {
    render(
      <SendServiceRecordsLinkModal
        open
        customer={baseCustomer({ is_muted: true })}
        onClose={() => {}}
        onSent={() => {}}
        onError={() => {}}
      />,
    );
    const emailTab = await screen.findByTestId("sr-link-tab-email");
    const smsTab = screen.getByTestId("sr-link-tab-sms");
    expect(emailTab.getAttribute("data-disabled")).toBe("true");
    expect(smsTab.getAttribute("data-disabled")).toBe("true");
    expect(emailTab.getAttribute("title")).toMatch(/muted/i);
    expect(smsTab.getAttribute("title")).toMatch(/muted/i);
    // Consent banner visible for whichever tab is active.
    expect(screen.getByTestId("sr-link-consent-banner").textContent)
      .toMatch(/muted/i);
    // Send disabled.
    expect(screen.getByTestId("sr-link-send").disabled).toBe(true);
  });

  it("passes the recipient override through to the send payload", async () => {
    postSpy.mockResolvedValueOnce({
      ok: true,
      url: "https://portal.example/api/portal/auto-login?t=x&redirect=/portal/service-reports",
      recipient: "second@example.com",
      channel: "email",
      ttl_hours: 168,
      expires_at: "2026-02-14T12:00:00+00:00",
    });
    render(
      <SendServiceRecordsLinkModal
        open
        customer={baseCustomer()}
        onClose={() => {}}
        onSent={() => {}}
        onError={() => {}}
      />,
    );
    const input = await screen.findByTestId("sr-link-recipient");
    fireEvent.change(input, { target: { value: "second@example.com" } });
    fireEvent.click(screen.getByTestId("sr-link-send"));
    await waitFor(() =>
      expect(postSpy).toHaveBeenCalledWith(
        "/customers/cust-1/send-service-records-link",
        { channel: "email", recipient: "second@example.com" },
      ),
    );
  });
});
