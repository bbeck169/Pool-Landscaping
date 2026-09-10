/**
 * Feb-2026 · Admin Add Card on File — email flow behavioural tests.
 *
 * Covers the FE toast truthfulness contract (the fix for the P1
 * "sending email…" silent-fail bug):
 *   1. Successful send → success toast names the actual recipient(s)
 *      (sent_email / sent_sms gate the "success" copy).
 *   2. Silent no-op (HTTP 200, sent_email:false, sent_sms:false) →
 *      the FE surfaces an error toast with the ``reason`` — it does
 *      NOT lie about success.
 *   3. Server 4xx/5xx with structured detail → the FE toast shows
 *      the server message, not a generic "failed" copy.
 *   4. Button label copy contract — reads "Add card on file", NOT
 *      the old "Send add-card link".
 */
import React from "react";
import {
  render, screen, waitFor, fireEvent, act,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

let _apiPostImpl = vi.fn();
vi.mock("@/api", () => ({
  api: { post: (...a) => _apiPostImpl(...a) },
}));


import CardOnFileWarningBanner from "@/components/customers/CardOnFileWarningBanner";


const _customer = {
  id: "cust-1",
  name: "Alice",
  effective_require_card_on_file: true,
  has_card_on_file: false,
};


beforeEach(() => {
  _apiPostImpl = vi.fn();
});


describe("Admin Add Card on File · email-flow toast truthfulness", () => {
  it("button label reads 'Add card on file', not the old 'Send add-card link'", async () => {
    _apiPostImpl.mockResolvedValue({
      sent_email: true, sent_sms: false,
      email_recipient: "a@x", outcome: "partial",
      channels: { email: { sent: true }, sms: { sent: false } },
    });
    render(<CardOnFileWarningBanner customer={_customer} />);
    const btn = await screen.findByTestId("card-on-file-send-link-btn");
    expect(btn.textContent).toContain("Add card on file");
    expect(btn.textContent).not.toContain("Send add-card link");
  });

  it("successful send fires onSent with the recipient list", async () => {
    _apiPostImpl.mockResolvedValue({
      sent_email: true, sent_sms: true,
      email_recipient: "a@x", sms_recipient: "+1555",
      outcome: "sent",
      channels: {
        email: { sent: true, status: "sent" },
        sms:   { sent: true, status: "sent" },
      },
    });
    const onSent = vi.fn();
    const onError = vi.fn();
    render(
      <CardOnFileWarningBanner
        customer={_customer} onSent={onSent} onError={onError}
      />,
    );
    fireEvent.click(await screen.findByTestId("card-on-file-send-link-btn"));
    await waitFor(() => expect(onSent).toHaveBeenCalled());
    expect(onError).not.toHaveBeenCalled();
    expect(onSent.mock.calls[0][0]).toContain("a@x");
    expect(onSent.mock.calls[0][0]).toContain("+1555");
    expect(_apiPostImpl).toHaveBeenCalledWith(
      "/customers/cust-1/send-card-add-link", {},
    );
  });

  it("silent no-op (200 with sent_email:false) fires onError, NOT onSent", async () => {
    _apiPostImpl.mockResolvedValue({
      sent_email: false, sent_sms: false,
      email_recipient: null, sms_recipient: null,
      outcome: "nothing_sent",
      reason: "Customer has no email or phone on file.",
    });
    const onSent = vi.fn();
    const onError = vi.fn();
    render(
      <CardOnFileWarningBanner
        customer={_customer} onSent={onSent} onError={onError}
      />,
    );
    fireEvent.click(await screen.findByTestId("card-on-file-send-link-btn"));
    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(onSent).not.toHaveBeenCalled();
    expect(onError.mock.calls[0][0]).toContain(
      "no email or phone",
    );
  });

  it("server 4xx with structured detail surfaces the server message", async () => {
    const err = Object.assign(new Error("bad"), {
      detail: {
        code: "NO_CONTACT_ON_FILE",
        message: "Customer has no email or phone on file. Add contact info and try again.",
      },
    });
    _apiPostImpl.mockRejectedValue(err);
    const onSent = vi.fn();
    const onError = vi.fn();
    render(
      <CardOnFileWarningBanner
        customer={_customer} onSent={onSent} onError={onError}
      />,
    );
    fireEvent.click(await screen.findByTestId("card-on-file-send-link-btn"));
    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(onError.mock.calls[0][0]).toContain(
      "Add contact info and try again",
    );
    expect(onSent).not.toHaveBeenCalled();
  });

  it("rate-limit 429 renders the friendly retry hint", async () => {
    const err = Object.assign(new Error("rl"), {
      detail: { code: "RATE_LIMITED",
                message: "1 send per 5 min per customer" },
    });
    _apiPostImpl.mockRejectedValue(err);
    const onError = vi.fn();
    render(
      <CardOnFileWarningBanner
        customer={_customer} onError={onError}
      />,
    );
    fireEvent.click(await screen.findByTestId("card-on-file-send-link-btn"));
    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(onError.mock.calls[0][0]).toContain("wait a few minutes");
  });
});
