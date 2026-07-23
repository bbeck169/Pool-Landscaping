/**
 * Phase 15 · Feb-2026 — Mass Messaging compose dialog unit tests.
 *
 *  1. Send button is disabled until (a) at least one channel is
 *     selected AND (b) a body is provided.
 *  2. Clicking Send Now opens the confirmation modal BEFORE the
 *     network request fires.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// vi.mock is hoisted — declare the mock fns via vi.hoisted so they're
// available inside the factory and to the test body.
const { apiPostMock, apiGetMock } = vi.hoisted(() => ({
  apiPostMock: vi.fn(),
  apiGetMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { post: apiPostMock, get: apiGetMock },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
}));

import MassMessagingComposeDialog from
  "@/components/mass-messaging/MassMessagingComposeDialog";

const noop = () => {};

beforeEach(() => {
  apiGetMock.mockReset();
  apiGetMock.mockResolvedValue({ items: [] });
  apiPostMock.mockReset();
});

describe("MassMessagingComposeDialog", () => {
  it("Send button is disabled when no channel is selected", async () => {
    // Preview returns 0 recipients so canSend is false regardless.
    apiPostMock.mockResolvedValue({
      estimated_recipients: { email: 0, sms: 0 },
      stats: {
        audience_size: 0,
        email_eligible: 0, sms_eligible: 0,
        no_contact_email: 0, no_contact_sms: 0,
        suppressed_email: 0, suppressed_sms: 0,
      },
      sample_render: { email_subject: "", email_body_html: "", sms_body: "" },
      confirm_token: "tok-empty",
      estimated_cost_hint: 0,
      audience_cap: 5000,
    });

    render(<MassMessagingComposeDialog open onOpenChange={noop} />);

    // Uncheck both channels — Send should stay disabled.
    const emailBox = await screen.findByTestId("mass-messaging-channel-email-checkbox");
    const smsBox = screen.getByTestId("mass-messaging-channel-sms-checkbox");
    fireEvent.click(emailBox);
    fireEvent.click(smsBox);

    const send = screen.getByTestId("mass-messaging-send-btn");
    expect(send).toBeDisabled();
  });

  it("Send button enables when channels + body + non-zero recipients + confirm_token are set", async () => {
    apiPostMock.mockResolvedValue({
      estimated_recipients: { email: 3, sms: 3 },
      stats: {
        audience_size: 3,
        email_eligible: 3, sms_eligible: 3,
        no_contact_email: 0, no_contact_sms: 0,
        suppressed_email: 0, suppressed_sms: 0,
      },
      sample_render: {
        email_subject: "Hello Alice",
        email_body_html: "Hi Alice",
        sms_body: "Hi Alice",
        unresolved_tokens: [],
      },
      confirm_token: "tok-3",
      estimated_cost_hint: 0.03,
      audience_cap: 5000,
    });

    render(<MassMessagingComposeDialog open onOpenChange={noop} />);

    // Default state has both channels on + body pre-filled. Wait for
    // the debounced preview to land and enable the button.
    await waitFor(
      () => expect(screen.getByTestId("mass-messaging-send-btn")).toBeEnabled(),
      { timeout: 3000 },
    );

    // Preview summary should reflect the mocked totals.
    const summary = screen.getByTestId("mass-messaging-preview-summary");
    expect(summary.textContent).toMatch(/6 recipients/);
    expect(summary.textContent).toMatch(/3 via email/);
    expect(summary.textContent).toMatch(/3 via SMS/);
  });

  it("clicking Send Now opens the confirmation modal BEFORE calling /send", async () => {
    apiPostMock.mockResolvedValue({
      estimated_recipients: { email: 2, sms: 0 },
      stats: {
        audience_size: 2,
        email_eligible: 2, sms_eligible: 0,
        no_contact_email: 0, no_contact_sms: 2,
        suppressed_email: 0, suppressed_sms: 0,
      },
      sample_render: {
        email_subject: "Hi",
        email_body_html: "Body",
        unresolved_tokens: [],
      },
      confirm_token: "tok-2",
      estimated_cost_hint: 0.002,
      audience_cap: 5000,
    });

    render(<MassMessagingComposeDialog open onOpenChange={noop} />);

    await waitFor(
      () => expect(screen.getByTestId("mass-messaging-send-btn")).toBeEnabled(),
      { timeout: 3000 },
    );

    // Reset the mock so we can assert the send call was NOT made yet.
    apiPostMock.mockClear();

    fireEvent.click(screen.getByTestId("mass-messaging-send-btn"));

    // Confirmation modal must be visible now.
    await waitFor(
      () => expect(
        screen.getByTestId("mass-messaging-confirm-modal")
      ).toBeInTheDocument()
    );

    // No /send call should have fired at this stage.
    expect(
      apiPostMock.mock.calls.filter(([url]) =>
        url === "/mass-messaging/send").length
    ).toBe(0);
  });
});
