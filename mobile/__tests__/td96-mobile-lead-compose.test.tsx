/**
 * TD-96-mobile · LeadComposeSheet (port of web LeadComposeModal.jsx).
 * POST /leads/{id}/send-sms {body, override_consent}
 * POST /leads/{id}/send-email {subject, body, override_consent}
 */
import React from "react";
import { render, fireEvent, act } from "@testing-library/react-native";

const mockPost = jest.fn();
const mockToast = jest.fn();

jest.mock("@/src/api", () => {
  class ApiError extends Error {
    status: number; detail: any;
    constructor(msg: string, status: number, detail: any) { super(msg); this.status = status; this.detail = detail; }
  }
  return { api: { post: (u: string, b?: any) => mockPost(u, b) }, ApiError };
});
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));

import { ApiError } from "@/src/api";
import LeadComposeSheet from "@/src/components/leads/LeadComposeSheet";

const LEAD = { id: "L1", name: "Lena Lead", phone: "+15550001111", email: "lena@x.com" };
const onClose = jest.fn();

beforeEach(() => { mockPost.mockReset().mockResolvedValue({ status: "sent" }); mockToast.mockClear(); onClose.mockClear(); });

const mount = (channel: "sms" | "email", lead: any = LEAD) =>
  render(<LeadComposeSheet lead={lead} channel={channel} onClose={onClose} />);
const disabled = (q: any) => q.getByTestId("lead-compose-send").props.accessibilityState?.disabled;
const send = async (q: any) => { await act(async () => { fireEvent.press(q.getByTestId("lead-compose-send")); }); };

it("B1 · SMS: empty / whitespace body → send disabled; To line shows phone + name", () => {
  const q = mount("sms");
  expect(disabled(q)).toBe(true);
  fireEvent.changeText(q.getByTestId("lead-compose-body"), "   ");
  expect(disabled(q)).toBe(true);
  expect(q.getByTestId("lead-compose-to").props.children).toContain("+15550001111");
  expect(q.getByTestId("lead-compose-to").props.children).toContain("Lena Lead");
  expect(q.queryByTestId("lead-compose-subject")).toBeNull();
});

it("B2 · SMS 161 chars → multi-segment warning, still sendable", () => {
  const q = mount("sms");
  fireEvent.changeText(q.getByTestId("lead-compose-body"), "a".repeat(161));
  expect(q.getByTestId("lead-compose-char-counter").props.children).toBe("161 / 1600 · will send as multi-segment SMS");
  expect(disabled(q)).toBe(false);
});

it("B3 · SMS 1601 chars → over-cap text, send disabled", () => {
  const q = mount("sms");
  fireEvent.changeText(q.getByTestId("lead-compose-body"), "a".repeat(1601));
  expect(q.getByTestId("lead-compose-char-counter").props.children).toBe("1601 / 1600 · over the 1600-character cap");
  expect(disabled(q)).toBe(true);
});

it("B4 · SMS send OK → exact payload, success toast, closes", async () => {
  const q = mount("sms");
  fireEvent.changeText(q.getByTestId("lead-compose-body"), "Hi Lena");
  await send(q);
  expect(mockPost).toHaveBeenCalledWith("/leads/L1/send-sms", { body: "Hi Lena", override_consent: false });
  expect(mockToast).toHaveBeenCalledWith("SMS sent", "success");
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("B5 · Email needs subject AND body → payload {subject, body, override_consent}", async () => {
  const q = mount("email");
  expect(q.getByTestId("lead-compose-to").props.children).toContain("lena@x.com");
  fireEvent.changeText(q.getByTestId("lead-compose-body"), "Body text");
  expect(disabled(q)).toBe(true);
  fireEvent.changeText(q.getByTestId("lead-compose-subject"), "Your quote");
  expect(disabled(q)).toBe(false);
  await send(q);
  expect(mockPost).toHaveBeenCalledWith("/leads/L1/send-email", { subject: "Your quote", body: "Body text", override_consent: false });
  expect(mockToast).toHaveBeenCalledWith("Email sent", "success");
});

it("B6 · sms_ok:false → consent warning; send blocked until override; payload override_consent:true", async () => {
  const q = mount("sms", { ...LEAD, sms_ok: false });
  expect(q.getByTestId("lead-compose-consent-warning")).toBeTruthy();
  fireEvent.changeText(q.getByTestId("lead-compose-body"), "Hi");
  expect(disabled(q)).toBe(true);
  fireEvent.press(q.getByTestId("lead-compose-override"));
  expect(q.getByTestId("lead-compose-override").props.accessibilityState?.checked).toBe(true);
  expect(disabled(q)).toBe(false);
  await send(q);
  expect(mockPost).toHaveBeenCalledWith("/leads/L1/send-sms", { body: "Hi", override_consent: true });
  // email_ok absent → no warning on the email channel (absent means OK)
  expect(mount("email", { ...LEAD, sms_ok: false }).queryByTestId("lead-compose-consent-warning")).toBeNull();
});

it("B7 · provider status failed → error toast with row.error, still closes (web parity)", async () => {
  mockPost.mockResolvedValueOnce({ status: "failed", error: "Carrier rejected" });
  const q = mount("sms");
  fireEvent.changeText(q.getByTestId("lead-compose-body"), "Hi");
  await send(q);
  expect(mockToast).toHaveBeenCalledWith("SMS failed — Carrier rejected", "error");
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("B8 · ApiError dict detail {code:consent_required, message} → toast shows message; string detail as-is; sheet stays open", async () => {
  mockPost.mockRejectedValueOnce(new (ApiError as any)("Bad request", 400, { code: "consent_required", message: "This lead has opted out of SMS." }));
  const q = mount("sms");
  fireEvent.changeText(q.getByTestId("lead-compose-body"), "Hi");
  await send(q);
  expect(mockToast).toHaveBeenLastCalledWith("This lead has opted out of SMS.", "error");
  mockPost.mockRejectedValueOnce(new (ApiError as any)("Bad request", 400, "Lead has no phone number on file"));
  await send(q);
  expect(mockToast).toHaveBeenLastCalledWith("Lead has no phone number on file", "error");
  expect(onClose).not.toHaveBeenCalled();
});

it("B9 · cancel / close → onClose, no API call", () => {
  const q = mount("email");
  fireEvent.press(q.getByTestId("lead-compose-cancel"));
  fireEvent.press(q.getByTestId("lead-compose-close"));
  expect(onClose).toHaveBeenCalledTimes(2);
  expect(mockPost).not.toHaveBeenCalled();
});
