/**
 * Phase L3 · Feb-2026 · LeadComposeModal vitest.
 *
 * Coverage:
 *  1. SMS char counter — no warn ≤ 160, warn class flips > 160.
 *  2. Consent warning renders when ``sms_ok === false``; the primary
 *     button is disabled until the Override checkbox is ticked, then
 *     it unlocks.
 *  3. Truthful toast on mocked provider failure — the modal calls the
 *     ``sonner`` error toast (NOT success) when the row comes back
 *     with ``status="failed"``.
 *  4. Email flavor renders the subject input; the send button is
 *     disabled until subject + body are both non-empty.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

const _post = vi.fn();
vi.mock("@/api", () => ({
  api: { post: (...args) => _post(...args) },
}));

const _toastError = vi.fn();
const _toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    error: (...a) => _toastError(...a),
    success: (...a) => _toastSuccess(...a),
  },
}));

// eslint-disable-next-line import/first
import LeadComposeModal from "../pages/leads/LeadComposeModal";

const LEAD_OK = {
  id: "lead-1", name: "Alice",
  phone: "+15555550100", email: "alice@example.com",
  sms_ok: true, email_ok: true,
};
const LEAD_OPT_OUT_SMS = { ...LEAD_OK, sms_ok: false };

beforeEach(() => {
  _post.mockReset();
  _toastError.mockReset();
  _toastSuccess.mockReset();
});

describe("LeadComposeModal · SMS char counter", () => {
  it("shows plain counter under 160, flips to warn class over 160", () => {
    render(
      <LeadComposeModal lead={LEAD_OK} channel="sms"
                          onClose={() => {}} onSent={() => {}} />,
    );
    const counter = screen.getByTestId("lead-compose-char-counter");
    const body = screen.getByTestId("lead-compose-body");
    // Under 160 → no warn.
    fireEvent.change(body, { target: { value: "hello" } });
    expect(counter.textContent).toMatch(/5 \/ 1600/);
    expect(counter.className).not.toMatch(/text-amber-700|text-rose-700/);
    // Over 160 → warn class.
    fireEvent.change(body, { target: { value: "x".repeat(161) } });
    expect(counter.className).toMatch(/text-amber-700/);
    expect(counter.textContent).toMatch(/multi-segment/);
  });
});

describe("LeadComposeModal · consent gate", () => {
  it("renders warning when sms_ok=false and unlocks send on override", () => {
    render(
      <LeadComposeModal lead={LEAD_OPT_OUT_SMS} channel="sms"
                          onClose={() => {}} onSent={() => {}} />,
    );
    expect(
      screen.getByTestId("lead-compose-consent-warning"),
    ).toBeInTheDocument();

    const body = screen.getByTestId("lead-compose-body");
    fireEvent.change(body, { target: { value: "Hi following up" } });

    const sendBtn = screen.getByTestId("lead-compose-send");
    // Still disabled because override checkbox not ticked yet.
    expect(sendBtn).toBeDisabled();

    // Flip the override — send unlocks.
    fireEvent.click(screen.getByTestId("lead-compose-override"));
    expect(sendBtn).not.toBeDisabled();
  });
});

describe("LeadComposeModal · truthful toast on failure", () => {
  it("shows an error toast when the backend row returns status=failed", async () => {
    _post.mockResolvedValue({
      id: "c1", status: "failed", channel: "sms",
      error: "resend refused",
      provider_status_raw: "failed",
    });
    const onSent = vi.fn();
    render(
      <LeadComposeModal lead={LEAD_OK} channel="sms"
                          onClose={() => {}} onSent={onSent} />,
    );
    fireEvent.change(screen.getByTestId("lead-compose-body"),
                       { target: { value: "Hi" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("lead-compose-send"));
      await Promise.resolve();
    });
    expect(_post).toHaveBeenCalledWith(
      "/leads/lead-1/send-sms",
      { body: "Hi", override_consent: false },
    );
    expect(_toastError).toHaveBeenCalled();
    expect(_toastSuccess).not.toHaveBeenCalled();
  });
});

describe("LeadComposeModal · email flavor", () => {
  it("renders subject input; send stays disabled until subject+body non-empty", () => {
    render(
      <LeadComposeModal lead={LEAD_OK} channel="email"
                          onClose={() => {}} onSent={() => {}} />,
    );
    const subject = screen.getByTestId("lead-compose-subject");
    const body = screen.getByTestId("lead-compose-body");
    const sendBtn = screen.getByTestId("lead-compose-send");

    expect(subject).toBeInTheDocument();
    expect(sendBtn).toBeDisabled();

    fireEvent.change(subject, { target: { value: "Following up" } });
    expect(sendBtn).toBeDisabled(); // body still empty

    fireEvent.change(body, { target: { value: "Hi Alice" } });
    expect(sendBtn).not.toBeDisabled();
  });
});
